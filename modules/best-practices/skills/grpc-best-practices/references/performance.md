# GRPC performance rules

Detailed entries for `GRPC-016..GRPC-017`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GRPC-016 — Reuse one client connection per backend; never dial per call; set keepalive

**What.** Create one `grpc.ClientConn` per backend at startup and share it
across all requests — HTTP/2 multiplexes many concurrent RPCs over the same
connection(s). Don't build a new connection per call. Enable keepalive so idle
connections detect dead peers instead of failing silently on the first use.

**Why.** Each dial costs a TCP + TLS handshake and a fresh HTTP/2 connection —
per-call connection building multiplies latency (and certificate verification)
and connection churn. Without keepalive, a stale pooled connection pointing at
a dead pod fails lazily — the first RPC after the peer died hangs or errors
instead of reconnecting, which looks like a random service blip. One shared
connection treats HTTP/2's multiplexing as the feature it is.

**How.**

```go
conn, err := grpc.NewClient("users:50051", grpc.WithTransportCredentials(
    insecure.NewCredentials())) // insecure: local dev only — production uses TLS creds (GRPC-018)
if err != nil {
    return err
}

client := pb.NewUsersClient(conn)   // same conn shared by every request handler
```

Keepalive (client side):

```go
grpc.WithKeepaliveParams(keepalive.ClientParameters{
    Time:                30 * time.Second,
    Timeout:             10 * time.Second,
    PermitWithoutStream: true,   // ping even with no active RPC
})
```

**When NOT to apply.** Short-lived CLI tools dial once per run anyway — reuse
within the run. Each distinct backend address gets its own connection: "shared"
means one per (client process, backend), not one global connection for
everything. Microbenchmark-level callers that need sub-ms reuse may tune
connection pools, but the default shape is one shared client.

---

## GRPC-017 — Set `MaxRecvMsgSize`/`MaxSendMsgSize` deliberately; the 4 MiB default fails loudly

**What.** The grpc-go default *receive* limit is 4 MiB per message on both
client and server (the default *send* limit is `math.MaxInt32` — effectively
uncapped on both sides), so an oversized message is normally rejected by the
receiver at runtime with a resource error. Set
`grpc.MaxRecvMsgSize`/`grpc.MaxSendMsgSize` (server) and
`grpc.MaxCallRecvMsgSize`/`grpc.MaxCallSendMsgSize` (client) deliberately when
your payloads legitimately exceed it — and prefer streaming or batching
(GRPC-009) over raising the cap to hide an oversized-payload design.

**Why.** A message over the receiver's 4 MiB cap fails only at runtime — and
because the sender is uncapped by default, the failure lands on the *other*
side: "worked in tests, fails in prod" the moment a row embeds a big blob.
That loud failure is a feature: it surfaces accidental oversized payloads
instead of silently degrading. Raising
the limit to a huge value hides the real problem and invites memory spikes —
one 2 GiB message means ~2 GiB of RAM on both sides, plus copies during
deserialization.

**How.**

```go
s := grpc.NewServer(
    grpc.MaxRecvMsgSize(16 << 20), // 16 MiB — deliberate, documented ceiling
)

conn, err := grpc.NewClient(addr,
    grpc.WithTransportCredentials(insecure.NewCredentials()), // local dev only (GRPC-018)
    grpc.WithDefaultCallOptions(
        grpc.MaxCallRecvMsgSize(16 << 20),
        grpc.MaxCallSendMsgSize(16 << 20),
    ),
)
if err != nil {
    return err
}
```

If you repeatedly approach the cap, stream the data (GRPC-009-010) instead of
ratcheting the limit.

**When NOT to apply.** Unary download/upload RPCs that legitimately need tens
of megabytes (bounded, fits memory) can raise the cap — pair it with a
documented ceiling agreed on both sides. Server streaming is the right answer
for multi-hundred-MB payloads; don't size individual messages for that.

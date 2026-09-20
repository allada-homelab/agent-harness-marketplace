# GRPC security rules

Detailed entries for `GRPC-018`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GRPC-018 — Run production gRPC over TLS; `insecure.NewCredentials()` is dev-only

**What.** Every production server sets transport credentials —
`grpc.Creds(credentials.NewServerTLSFromFile(certFile, keyFile))`, or
`credentials.NewTLS(*tls.Config)` when you need client-cert verification
(mTLS) or a pinned minimum version. Clients pair it with
`grpc.WithTransportCredentials(credentials.NewTLS(...))` or
`credentials.NewClientTLSFromFile(caFile, serverNameOverride)`.
`insecure.NewCredentials()` belongs on localhost and in tests, nowhere else.

**Why.** grpc-go refuses to dial with no credential option at all — and the fix
it suggests in its own error text is `grpc.WithTransportCredentials(insecure.NewCredentials())`,
so the plaintext path is the one people paste and forget. Everything then
crosses the network in the clear: message bodies *and* the metadata carrying
bearer tokens and API keys, readable by anything on the path. gRPC pushes back
where it can — attach a token with `grpc.WithPerRPCCredentials` whose
`RequireTransportSecurity()` returns true over an insecure connection and
`grpc.NewClient` fails with `grpc: the credentials require transport level
security`. A credential type that returns `false` there gets no such warning
and ships your token in plaintext.

**How.**

```go
// Server
creds, err := credentials.NewServerTLSFromFile("server.crt", "server.key")
if err != nil {
    return err
}
s := grpc.NewServer(grpc.Creds(creds))

// Client — system roots, server name from the target authority
conn, err := grpc.NewClient("users.example.com:443",
    grpc.WithTransportCredentials(credentials.NewTLS(&tls.Config{
        MinVersion: tls.VersionTLS13,
    })))
```

For mTLS give the server a `tls.Config` with `ClientCAs` and
`ClientAuth: tls.RequireAndVerifyClientCert`, and the client one carrying its
own `Certificates`. GRPC-016 and GRPC-017's snippets use
`insecure.NewCredentials()` for brevity and say so inline — take transport
credentials from here, not from there.

**When NOT to apply.** Two honest carve-outs. A service mesh (Istio, Linkerd)
that terminates mTLS in a sidecar wants the process itself listening plaintext
on loopback — the mesh owns the crypto and issues the workload identity, and
double-encrypting hides it. Same for a TLS-terminating load balancer on a
segment you actually control. Both are trade-offs to state out loud: you have
moved the security boundary to the sidecar or the proxy, and the hop behind it
is only as private as the node. "It's an internal network," with no mesh and no
terminating proxy, is the excuse, not the exception.

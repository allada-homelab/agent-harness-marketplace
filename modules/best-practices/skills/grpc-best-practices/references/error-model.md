# GRPC error-model rules

Detailed entries for `GRPC-004..GRPC-006`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GRPC-004 — Return canonical `google.rpc.Code` values mapped from your domain; never invent codes

**What.** Errors use the canonical codes from `google.rpc.Code` (16 error codes
plus `OK`) —
`NOT_FOUND`, `INVALID_ARGUMENT`, `PERMISSION_DENIED`, `UNAUTHENTICATED`,
`RESOURCE_EXHAUSTED`, `UNAVAILABLE`, `DEADLINE_EXCEEDED`, `INTERNAL`, ... —
returned via `status.Error(codes.X, "message")`. Map your domain conditions
onto them; never invent new codes and never return HTTP-flavored payloads
("404 Not Found" as text) or transport-specific codes.

**Why.** Clients write handling logic against the *code*: retry on
`UNAVAILABLE`/`DEADLINE_EXCEEDED`, refresh credentials on `UNAUTHENTICATED`,
bail on `INTERNAL`. Ad-hoc codes and HTTP-looking strings break automation — a
client seeing `"HTTP 404"` as message text can't branch, retries misfire, and
an `INTERNAL`-worth crash surfaced as `NOT_FOUND` misroutes load. The canonical
set also maps cleanly to HTTP statuses for gRPC-Gateway/transcoding.

**How.**

```go
// grpc-go — return via the status package in the handler/service
return status.Error(codes.NotFound, "user not found")

// typical mapping
not found            -> codes.NotFound
bad request input    -> codes.InvalidArgument
authn failed         -> codes.Unauthenticated
authz failed         -> codes.PermissionDenied
rate limited/abuse   -> codes.ResourceExhausted
backend exploded     -> codes.Internal
cancelled            -> context.Canceled (grpc-go maps automatically)
```

**When NOT to apply.** Choosing *which* canonical code is judgment per error
(`RESOURCE_EXHAUSTED` vs `UNAVAILABLE`); the rule is that it is one of the 16
and reflects the client's actual recovery behavior. Cross-service protocols
with deliberate replay semantics may deviate — document it publicly.

---

## GRPC-005 — Add machine-readable detail with `google.rpc.ErrorInfo`/`status.WithDetails`

**What.** When a client must branch programmatically — refresh a token, change
scope, retry with a backoff hint, show specific copy — attach structured detail
via `google.rpc.ErrorInfo` (fields: `reason`, `domain`, `metadata`) with
`status.New(...).WithDetails(...)`. Reserve the human message for logs and UI.

**Why.** The code alone (`PERMISSION_DENIED`) doesn't tell a program *why* or
*what to do*; parsing the human message string for behavior is brittle
(localization, drift, non-contract text). Encoding the reason as data — e.g.
`reason: "SCOPE_UPGRADE_REQUIRED"` with the offending scope in `metadata` —
lets a client branch on a stable, typed value.

**How.**

```go
st := status.New(codes.PermissionDenied, "scope not allowed")
if st2, err := st.WithDetails(&errdetails.ErrorInfo{
    Reason:   "SCOPE_UPGRADE_REQUIRED",
    Domain:   "iam.example.com",
    Metadata: map[string]string{"user_id": uid},
}); err == nil {
    st = st2
}
return st.Err()
```

Client reads it back with `status.Convert(err)` and ranges over `st.Details()`,
which yields already-unmarshalled detail messages to type-assert:

```go
st := status.Convert(err)
for _, d := range st.Details() {
    if info, ok := d.(*errdetails.ErrorInfo); ok {
        // branch on info.GetReason() / info.GetMetadata()
    }
}
```

**When NOT to apply.** Terminal, self-explanatory errors (`NOT_FOUND` with the
ID in the message) don't need detail — add it the moment a client must branch.
Always check the error returned by `WithDetails` (it can fail for unregistered
detail types); never ignore it silently.

---

## GRPC-006 — Translate internal errors to gRPC status only at the service boundary

**What.** The service boundary is where plain errors become gRPC errors. Don't
let raw database errors, stack traces, exception classes, or internal type
names escape. Log the cause server-side (with an ID), and map unknown/foreign
failures to `codes.Internal` with a generic message.

**Why.** A leaked SQL error or raw stack is a debugging gift to anyone probing
your service — and often PII (a row value appears in the error text). An
unknown failure must degrade to `INTERNAL`, never to a misleading specific
code a client will act on wrongly. Translating at the boundary also keeps the
rest of the codebase free of gRPC-isms: handlers return plain Go errors, and
one interceptor/service maps them (the gRPC analog of GO-006's boundary
discipline).

**How.**

```go
func (s *usersSvc) GetUser(ctx context.Context, req *pb.GetUserRequest) (*pb.User, error) {
    u, err := s.repo.Find(ctx, req.UserId)
    if err != nil {
        slog.Error("get user failed", "user_id", req.UserId, "err", err) // server-side only
        return nil, status.Error(codes.Internal, "internal error")
    }
    if u == nil {
        return nil, status.Error(codes.NotFound, "user not found")
    }
    return u.ToProto(), nil
}
```

**When NOT to apply.** Client-side, or internal in-process calls: mapping there
is waste — do it at the process boundary (public RPC methods, gateways). In a
dev environment you control, returning more detail is fine, but keep mapping in
one place so prod behavior is uniform.

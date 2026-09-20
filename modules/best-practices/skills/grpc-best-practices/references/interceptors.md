# GRPC interceptor rules

Detailed entries for `GRPC-011..GRPC-013`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GRPC-011 — Cross-cutting concerns (auth, logging, recovery, validation) live in interceptors, with deliberate ordering

**What.** Authentication/authorization, request logging with IDs, rate
limiting, panic recovery, and validation are interceptors — not loops of
copy-pasted code in each handler. Wire them with
`grpc.ChainUnaryInterceptor` / `grpc.ChainStreamInterceptor` and order them
deliberately: recovery outermost, then auth, then logging, then validation,
then the handler.

**Why.** Copy-pasted concern code drifts — one handler forgets auth and you
have an unauthenticated RPC; one logs without IDs and audits break. Interceptors
make behavior uniform (every method gets the same auth check, log line, and
request ID), give a single review point, and compose predictably. Order matters
because the chain runs outside-in: recovery must see panics from everything
inside it, auth must run before validation, and handler-adjacent work runs
last.

**How.**

```go
s := grpc.NewServer(
    grpc.ChainUnaryInterceptor(
        recovery.UnaryServerInterceptor(),   // outermost: a panic never escapes below
        auth.UnaryServerInterceptor(),       // authn/authz before anything handler-like
        logz.UnaryServerInterceptor(),       // request-ID logging
        validate.UnaryServerInterceptor(),   // schema validation, closest to the handler
    ),
)
```

Register the equivalent stream chain for streaming RPCs — unary interceptors do
not cover streams.

**When NOT to apply.** Per-RPC behavior that only that handler understands stays
in the handler. Interceptors run on every request's hot path — keep them fast
and side-effect-free on success; expensive work (per-call heavy crypto, remote
calls) needs cacheing or a per-handler design.

---

## GRPC-012 — Recover panics in a server interceptor; grpc-go has none built in

**What.** Install a recovery interceptor so a panicking handler converts to
`codes.Internal` and the server keeps serving. Log the panic with its stack.

**Why.** An uncaught panic in grpc-go kills the process: the serving goroutine
panics and gRPC does not recover it. One malformed input that nil-derefs any
handler restarts/crashes the whole service — the classic "input triggers a
crash" availability failure. Recovery at the interceptor is the gRPC analog of
GO-006's process-boundary discipline, at the right unit (per-method, not
per-process).

**How.**

```go
func unaryRecovery(ctx context.Context, req any,
    info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (resp any, err error) {
    defer func() {
        if r := recover(); r != nil {
            log.Printf("panic in %v: %v\n%s", info.FullMethod, r, debug.Stack())
            err = status.Error(codes.Internal, "internal error")
        }
    }()
    return handler(ctx, req)
}

s := grpc.NewServer(grpc.UnaryInterceptor(unaryRecovery))
// add the stream equivalent for streaming handlers
```

**When NOT to apply.** Recovery is a safety net, not a license to panic — a
codebase that expects recovery masks bugs (GO-006 still applies inside each
handler). Register the *stream* interceptor distinctly: unary recovery does not
cover streaming handlers.

---

## GRPC-013 — Validate with `buf.validate` + a protovalidate interceptor; return `INVALID_ARGUMENT`

**What.** Express validation constraints next to the fields in the `.proto`
(`buf.validate` annotations) and enforce them at the boundary with a
protovalidate interceptor on the server (and, for fast failure, the client).
On violation the standard interceptor returns `codes.InvalidArgument`.

**Why.** Hand-rolled `if req.X == "" { ... }` checks in every handler duplicate
the schema, drift when fields are added, and are easy to skip. Declared
constraints compile into the generated code — the server rejects the request
with `INVALID_ARGUMENT` *before* handler logic runs, the client fails fast on
its own bad output, and one source of truth (the schema) owns validation.

**How.**

```proto
message GetUserRequest {
  string user_id = 1 [(buf.validate.field).string = {min_len: 1}];
}
```

```go
import (
    "buf.build/go/protovalidate"
    protovalidate_mw "github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/protovalidate"
    "google.golang.org/grpc"
)

validator, err := protovalidate.New()   // compiles the buf.validate constraints once
if err != nil {
    return err
}

// the interceptor returns codes.InvalidArgument with a description of the violation
s := grpc.NewServer(grpc.UnaryInterceptor(protovalidate_mw.UnaryServerInterceptor(validator)))
```

**When NOT to apply.** Messages with genuinely no constraints don't need the
pass (it's cheap, but add it as rules come). Migrate large legacy schemas
incrementally — annotate as you go. Trust boundaries: always validate
server-side regardless; client validation is optimization. Don't keep
hand-rolled `Validate()` methods alongside protovalidate — replace them.

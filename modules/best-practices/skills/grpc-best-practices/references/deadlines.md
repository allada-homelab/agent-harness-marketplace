# GRPC deadline rules

Detailed entries for `GRPC-007..GRPC-008`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GRPC-007 — Clients set a deadline on every RPC

**What.** Every gRPC call runs under a deadline. Derive a timed context from
the caller's context and pass it to the call:

```go
ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
defer cancel()
resp, err := client.GetUser(ctx, req)
```

The deadline propagates to the server over the wire (`grpc-timeout` header);
the server then enforces the remaining budget. The same ctx bounds streaming
clients.

**Why.** Without a deadline, a hung peer leaves the call blocked indefinitely —
the caller's goroutine and connection never unwind, and the caller's own
callers wait behind it. In a chain of three services each blocking on the next
with no deadline, one slow leaf blocks N goroutines × requests across the
whole path — latency tails, goroutine leaks, and cascading timeouts. This is
the most common production gRPC failure mode, and setting a deadline is the
primary defense.

**How.**

```go
ctx, cancel := context.WithTimeout(parentCtx, 2*time.Second)
defer cancel()
resp, err := client.GetUser(ctx, req)
if errors.Is(err, context.DeadlineExceeded) {
    // call exceeded its budget — return or retry per your policy
    return nil, status.FromContextError(err).Err()
}
```

grpc-go maps `context.DeadlineExceeded` to `codes.DeadlineExceeded`
automatically.

**When NOT to apply.** Fire-and-forget or intentionally long-lived calls want a
very long deadline rather than none — an ID-less reconnect hang is the failure
you're guarding against. Long-poll/SSE-style APIs: keep a generous but finite
deadline per chunk. In all cases prefer *some* budget over zero.

---

## GRPC-008 — Handlers honor the context: check `ctx.Err()`, propagate downstream

**What.** A handler treats the incoming ctx as its deadline budget: check
`ctx.Err()` in loops and blocking waits, propagate ctx into every downstream
call (database, HTTP, another RPC), and return promptly when it fires. grpc-go
converts `context.DeadlineExceeded`/`context.Canceled` into the canonical codes
automatically when you return the context error.

**Why.** The server received a *remaining* budget; a handler that ignores it
keeps consuming CPU, database connections, and downstream RPCs after the caller
already gave up — "zombie requests" that turn deadline timeouts into resource
exhaustion. Honoring ctx is what makes client deadline propagation (GRPC-007)
stop work end-to-end instead of just making the caller wait.

**How.**

```go
func (s *svc) Drain(ctx context.Context, req *pb.DrainRequest) (*pb.Empty, error) {
    for {
        select {
        case <-ctx.Done():
            return nil, ctx.Err()   // grpc-go maps to DeadlineExceeded/Canceled
        case batch := <-s.jobs:
            if err := insert(ctx, batch); err != nil {
                return nil, err
            }
        }
    }
}
```

Downstream calls get the same ctx, or one derived with a **shorter** remaining
budget — never longer — e.g. `context.WithTimeout(ctx, 500*time.Millisecond)`.

**When NOT to apply.** Cleanup that must finish after the deadline (flush a
buffer, close a handle) runs in a fresh scoped context with its own short
timeout, not the request ctx — see GO-006/GO-008 for how to bound that without
leaking.

# GO concurrency & context rules

Detailed entries for `GO-007..GO-009`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GO-007 — Pass `context.Context` as the first parameter of blocking/I-O functions; never store it in a struct

**What.** Any function that blocks, hits the network, or touches the filesystem
takes `ctx context.Context` as its *first* parameter. Context is a flow value
passed down the call graph; it must never be stored in a struct field, global,
or one-off created per object and reused.

**Why.** Storing ctx on a struct decouples cancellation from the flow that owns
it. Two concurrent callers sharing one struct share one context — the faster or
the goroutine that exits cancels the other's work mid-flight, and the struct
outliving the request pins a stale deadline into every later call. The failure
is silent: calls appear to work until concurrent paths start hitting
`ctx.Err()`. `go vet` won't catch it — its `lostcancel` analyzer only flags a
`cancel` func that is never called — which is why the third-party `containedctx`
linter exists.

**How.**

```go
func (s *Server) Run(ctx context.Context) error { ... }   // good: flow value

// WRONG — context stored, cancellation decoupled from the flow
type Worker struct {
    ctx context.Context
}
```

Context is a value type — copying and passing it down as a parameter is *how*
propagation works; the prohibition is on long-term storage in state.

**When NOT to apply.** A background worker that owns its lifecycle may create
one `context.WithCancel` in its constructor — but it still passes that ctx to
each method rather than reading it from a field. `context.Background()` /
`context.TODO()` in tests, `main`, and top-level setup is normal (that's where
the root context comes from).

---

## GO-008 — Bound every goroutine's lifetime; a goroutine without a stop path is a leak

**What.** When you start a goroutine, you must be able to bound when it ends:
an associated cancelable context, a `done` channel, a `sync.WaitGroup`, or an
error group. Never fire `go func() { ... }()` fire-and-forget inside a request
path.

**Why.** Unbounded goroutines accumulate per request — each holds its stack and
often a reference to request-scoped state. Under load you get goroutine counts
and RSS climbing (visible in the pprof goroutine profile), log interleaving
from half-dead workers still touching the context after the request returned,
and — in the worst case — a server that does real work per abandoned request
long after the client left. A stop path is the difference between "cleans up on
cancel" and "leaks on cancel".

**How.**

```go
ctx, cancel := context.WithCancel(context.Background())
defer cancel()

done := make(chan struct{})
go func() {
    defer close(done)          // the stop signal
    work(ctx)
}()

select {
case <-done:                   // completed normally
case <-ctx.Done():             // canceled — bounded
}
```

Fan-out that should cancel as a group uses `errgroup` (GO-009) instead of
hand-rolled channels.

**When NOT to apply.** Truly fire-and-forget still needs a bound in practice:
send metrics/telemetry through a buffered channel drained by one goroutine
owned at process startup (bounded by process lifetime), rather than one
goroutine per request that may never flush before the process exits.

---

## GO-009 — Use `golang.org/x/sync/errgroup` for fan-out that cancels on first error

**What.** `errgroup.Group.Wait()` returns the first non-nil error from any
goroutine while still waiting for all of them; `errgroup.WithContext` derives a
child context canceled as soon as any goroutine returns a non-nil error. Use it
for parallel work whose failure should stop the rest.

**Why.** Hand-rolled `WaitGroup` + channel error plumbing has three recurring
bugs: it deadlocks when an error path forgets to send or reads a channel nobody
writes, it blocks forever reading a non-closed channel, and it *doesn't stop the
other goroutines* — siblings keep doing wasted work after the first failure.
`errgroup` encodes "first error cancels siblings" as the default, so siblings
checking `ctx` (GO-007/GO-008) stop early instead of burning time and upstream
quota.

**How.**

```go
import "golang.org/x/sync/errgroup"

g, ctx := errgroup.WithContext(ctx)
g.Go(func() error { return fetch(ctx, a) })
g.Go(func() error { return fetch(ctx, b) })
if err := g.Wait(); err != nil {
    return fmt.Errorf("fan-out failed: %w", err)
}
```

**When NOT to apply.** When you want *all* results regardless of errors
(partial-success semantics) — errgroup aborts propagation on the first error;
use `errgroup.Group` without `WithContext` or a plain `WaitGroup` if you must
collect every result. `errgroup` does not bound concurrency (no semaphore): a
worker pool needs an explicit cap (buffered-channel semaphore) on top. For a
trivial loop with no error path or I/O, a plain loop is simpler than any group.

# GO errors rules

Detailed entries for `GO-004..GO-006`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GO-004 — Wrap errors with `%w` to preserve the cause

**What.** When returning an error up the call stack, add context and keep the
cause addressable: `fmt.Errorf("load user %d: %w", id, err)`. Use the `%w`
verb, not `%v` or string concatenation, so `errors.Is` and `errors.As` still
see the wrapped cause.

**Why.** With `%v` or `fmt.Sprintf("%s: %v", ...)`, the cause is flattened into
text: `errors.Is(err, sql.ErrNoRows)` and type-based handling via `errors.As`
silently stop matching. The symptom is a handler that "never" catches its own
not-found/retryable error after one refactor added a wrap — a 500 where a 404
or a retry was intended. `%w` gives you both the readable stack in logs *and* a
cause chain the runtime can still traverse.

**How.**

```go
func LoadUser(ctx context.Context, id int64) (*User, error) {
    row, err := db.QueryRowContext(ctx, "...", id)
    if err != nil {
        return nil, fmt.Errorf("load user %d: %w", id, err)
    }
    ...
}
```

**When NOT to apply.** When the inner error must not escape — it carries a
secret, a host-specific path, or internal detail meant for server-side logs
only — wrap with `%v` (or a plain message) so the cause is hidden, and log the
real error inside. Use `errors.Join` (Go 1.20+) to group several independent
failures into one error that `errors.Is` still matches. Don't wrap an error
with no added context (`fmt.Errorf("%w", err)`) — that's pure noise.

---

## GO-005 — Match with `errors.Is` / `errors.As`, never `==`

**What.** Test for a specific error *value* (sentinel) with `errors.Is(err,
sentinel)` and for a specific error *type* with `errors.As(err, &target)` —
the error first, a pointer to the target variable second.
Comparing `err == sentinel` only works when the function you called returned
exactly that value, unwrapped.

**Why.** The moment any layer adds context with `%w` (GO-004) — which is the
recommended pattern everywhere — `==` starts returning false for the same
logical condition, silently. `errors.Is`/`As` walk the whole wrap chain. A
typical break shows up as "404 handling stopped working" right after someone
"improved" error messages, and nobody notices until a user hits the wrong
branch.

**How.**

```go
if errors.Is(err, sql.ErrNoRows) {
    return nil, errNotFound   // callers map this to 404 / NotFound
}

var netErr *net.OpError
if errors.As(err, &netErr) {
    // typed extraction — e.g. retry on transient network errors
    log.Printf("network op failed: %v", netErr)
}
```

`errors.As` walks the wrap chain (following `Unwrap`) and assigns the first
error whose type matches the target. Prefer it over a type switch on the raw
`err`, which only ever sees the outermost wrapper.

**When NOT to apply.** Direct `==` on errors you produced yourself in the same
scope and returned unwrapped is fine (rare). For *sentinel-style* errors that
will be wrapped elsewhere, prefer `errors.Is(err, sentinel)` even locally so
the comparison survives later rewraps.

---

## GO-006 — Return errors; don't `panic` or `os.Exit` in reusable code

**What.** Packages signal failure by returning an error. Reserve `panic` for
programmer errors (broken invariants, impossible states) and recover it only at
the outermost process boundary. `os.Exit` runs no deferred cleanup and should
never appear inside a library.

**Why.** A panicking library takes down the whole process with a stack trace a
caller can't intercept — the gRPC analog is a service that dies on one bad
request instead of returning `INTERNAL`. `os.Exit` is worse: it skips deferred
functions, so connection pools, flush buffers, and held locks leak or truncate
on the way out. Long-lived servers want a per-request error, not a crash.
`net/http` recovers handler panics in the serving goroutine, but `grpc-go` does
*not* — an uncaught handler panic takes the whole server process down unless you
install a recovery interceptor (see grpc-best-practices GRPC-012). Either way, a
panic in any *other* goroutine still kills the process.

**How.**

```go
func Save(ctx context.Context, u *User) error {
    if err := validate(u); err != nil {
        return err        // signal the caller; never crash
    }
    // ... persist
    return nil
}
```

**When NOT to apply.** `panic` (recovered locally, never leaking) is acceptable
for a narrow set: package-level `init` invariants, `json.Unmarshal` of a
statically-known constant you own, and as an internal control-flow hack in a
package whose public API only returns errors (e.g. an internal parser). At an
*exported* boundary, bad caller input is a data-validation error, not a
programming error — return an error. `os.Exit` belongs only in `main`/`init`
of a binary, after logging.

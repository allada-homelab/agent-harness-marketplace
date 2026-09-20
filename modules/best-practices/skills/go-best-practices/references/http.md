# GO HTTP rules (stdlib net/http)

Detailed entries for `GO-010..GO-011` and `GO-020`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GO-010 — Set timeouts on `http.Server`; wrap slow handlers in `http.TimeoutHandler`

**What.** An `http.Server{Addr: "..."}` with no timeouts accepts slowloris and
lets one slow client hold a connection forever. Set at least
`ReadHeaderTimeout`, and also `ReadTimeout`, `WriteTimeout`, `IdleTimeout`. For
handlers whose latency you don't control (a backend call, a big transform),
wrap them in `http.TimeoutHandler` so a dead dependency can't hold a connection
open.

**Why.** Go's `http.Server` defaults almost every timeout field to *zero*,
meaning "no timeout". A client that trickles bytes (slowloris, a stalled
mobile network) holds a goroutine + file descriptor indefinitely — a trivial
resource-exhaustion DoS on an internet-facing service, and a silent stranded
response on write for production traffic. Setting them is cheap; the default is
a footgun.

**How.**

```go
srv := &http.Server{
    Addr:              ":8080",
    ReadHeaderTimeout: 5 * time.Second,   // minimum you should always set
    ReadTimeout:       10 * time.Second,
    WriteTimeout:      30 * time.Second,
    IdleTimeout:       60 * time.Second,
    Handler:           mux,
}
```

Slow upstream behind a handler (server-side timeout, returns 503 on expiry):

```go
slow := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
    // calls an external API; may hang
})
mux.Handle("/expensive", http.TimeoutHandler(slow, 30*time.Second, "upstream timeout"))
```

**When NOT to apply.** `WriteTimeout` must exceed your *slowest legitimate*
response body. If you serve large downloads, SSE, or streaming, a short
`WriteTimeout` kills them — set `WriteTimeout: 0` and lean on
`ReadTimeout`/`IdleTimeout` plus each handler's own context and deadline.

---

## GO-011 — Outbound HTTP: carry context and give the client a timeout

**What.** Every outbound request runs under a deadline: either build a client
with a `Timeout`, or derive `req = req.WithContext(ctx)` from a caller context
that already has a deadline. Never rely on `http.DefaultClient`'s zero
`Timeout`, and always `defer resp.Body.Close()`.

**Why.** `http.DefaultClient` has no timeout, so an unresponsive peer blocks
the calling goroutine indefinitely — the client-side analog of GO-010, where
callers rarely run their own watchdog. One hung call in service A fans out into
leaked goroutines in every service waiting on A. Forgetting to close
`resp.Body` leaks a pooled connection (and prevents reuse under load).

**How.**

```go
client := &http.Client{Timeout: 10 * time.Second}

req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
if err != nil {
    return err
}
resp, err := client.Do(req)
if err != nil {
    return err
}
defer resp.Body.Close()
```

`req.WithContext(ctx)` and `client.Timeout` compose: a timeout of zero disables
the client-level cap, so keep the field non-zero unless the request context is
the only deadline source.

**When NOT to apply.** Long-lived streams (SSE, long-poll, WebSocket upgrade)
must *not* have an overall `Timeout` — they assert liveness with keepalive and
are bounded by `ctx` cancellation instead. Short-lived one-shot CLI calls can
use a plain `http.Get` only when you accept the zero-timeout default; prefer a
bounded client in anything that runs in a server.

---

## GO-020 — Shut down `http.Server` gracefully on SIGINT/SIGTERM

**What.** Don't let `srv.ListenAndServe()` be the last statement of your
program. Start the server in a goroutine, wait on a context from
`signal.NotifyContext(ctx, os.Interrupt, syscall.SIGTERM)`, then call
`srv.Shutdown` with a *fresh*, bounded context so in-flight requests drain
before the process exits. Treat `http.ErrServerClosed` from `ListenAndServe` as
the clean-shutdown sentinel, not a failure.

**Why.** Kubernetes rollouts, `docker stop`, and systemd restarts all deliver
SIGTERM, whose default disposition kills a Go process immediately. A server
with no shutdown path therefore hard-drops every request in flight the moment a
deploy starts: clients see connection resets and 502s, non-idempotent POSTs
land half-applied, and the error budget burns on every routine rollout rather
than on any actual bug. `Shutdown` instead closes the listeners, then idle
connections, then waits for active handlers to return. The paired footgun is
the sentinel: after `Shutdown`, `Serve`/`ListenAndServe` return
`http.ErrServerClosed` *immediately*, so a `log.Fatal(srv.ListenAndServe())`
kills the process mid-drain and reintroduces exactly the hard drop you added
shutdown to prevent.

**How.** Extends GO-001's `run(ctx) error` shape; the server goroutine has an
explicit stop path per GO-008.

```go
func run(ctx context.Context) error {
    ctx, stop := signal.NotifyContext(ctx, os.Interrupt, syscall.SIGTERM)
    defer stop()

    srv := &http.Server{Addr: ":8080", Handler: mux, ReadHeaderTimeout: 5 * time.Second}

    srvErr := make(chan error, 1)          // buffered: goroutine never blocks on exit
    go func() { srvErr <- srv.ListenAndServe() }()

    select {
    case err := <-srvErr:                  // failed to bind, or died on its own
        return err
    case <-ctx.Done():                     // signal arrived
    }

    // Fresh context — ctx is already canceled by the signal.
    shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
    defer cancel()
    if err := srv.Shutdown(shutdownCtx); err != nil {
        return err
    }
    if err := <-srvErr; !errors.Is(err, http.ErrServerClosed) {
        return err
    }
    return nil
}
```

Keep the drain budget under the platform's kill grace period (Kubernetes
defaults `terminationGracePeriodSeconds` to 30) so *you* decide what gets
dropped, not SIGKILL.

**When NOT to apply.** A short-lived CLI or one-shot job that holds no
connections doesn't need any of this. Two documented limits matter when it
does: `Shutdown` "does not attempt to close nor wait for hijacked connections
such as WebSockets" — a hijacked connection is terminal state the server no
longer owns — so a WebSocket/SSE service must notify those connections itself,
typically from a `srv.RegisterOnShutdown` hook (which per its own docs "should
start protocol-specific graceful shutdown, but should not wait for shutdown to
complete") plus its own connection registry. And if the shutdown context
expires, `Shutdown` returns the context's error with handlers still running;
reach for `srv.Close` only when you genuinely want the abrupt stop.

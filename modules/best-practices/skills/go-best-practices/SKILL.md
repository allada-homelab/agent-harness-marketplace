---
name: go-best-practices
description: Use when working with Go code — .go files and go.mod/go.sum, go build / go test / go test -race / go vet / gofmt / staticcheck / golangci-lint / govulncheck, module and package layout, error handling (errors.Is / %w), the context package, goroutines and channels, errgroup, stdlib net/http servers and clients, graceful shutdown on SIGINT/SIGTERM, parameterized SQL, or Go security (html/template, crypto/rand). Covers the GO- rule family (layout, errors, concurrency, HTTP, security, modules, quality, testing). Language-level Go only — container packaging lives in containers-best-practices, gRPC service rules in grpc-best-practices.
---

# Go best practices

A curated rule set for writing Go. Each rule has a stable ID and a
one-line summary. Full **What / Why / How / When-not-to-apply**
entries live in `references/`.

This skill is language-level Go. Container packaging rules live in
[`containers-best-practices`](../containers-best-practices/SKILL.md);
gRPC protocol and service rules live in
[`grpc-best-practices`](../grpc-best-practices/SKILL.md).

## When to apply this skill

Activate when any of these are true:

- A `.go` file, `go.mod`, or `go.sum` is in context.
- The user mentions Go modules, package layout, error handling, the `context` package, goroutines/channels, `net/http`, Go testing, or Go linting/vetting tools (`go fmt`/`gofmt`, `go vet`, `staticcheck`, `golangci-lint`).
- The user asks to review, fix, or write Go code, or to set up a Go project or CI gate.
- The user references a `GO-` rule ID.

## How to use the rule index

1. Scan the relevant section(s) below for rule IDs that apply to the current file.
2. For each rule you intend to apply or flag, open the corresponding `references/` file and read **only that rule's entry** — they're keyed by ID.
3. Cite the rule ID when you explain a change to the user.

## Rules — Layout

See [`references/layout.md`](./references/layout.md).

- **GO-001** — One Go module per repo; `go.mod` at the repo root, module path = canonical import path; keep `main()` a thin wrapper over a testable `run() error`.
- **GO-002** — Put private implementation under `internal/`; only public API lives above it.
- **GO-003** — Name the package after its directory; no `util`/`common`/`helpers` grab-bags.

## Rules — Errors

See [`references/errors.md`](./references/errors.md).

- **GO-004** — Wrap errors with `%w` to preserve the cause for `errors.Is`/`errors.As`.
- **GO-005** — Match with `errors.Is` / `errors.As`, never `==`.
- **GO-006** — Return errors, don't `panic`/`os.Exit` in reusable code; recover only at a process boundary.

## Rules — Concurrency & context

See [`references/concurrency.md`](./references/concurrency.md).

- **GO-007** — Pass `context.Context` as the first parameter of blocking/I-O functions; never store it in a struct field.
- **GO-008** — Bound every goroutine's lifetime with a stop path (WaitGroup, errgroup, cancelable ctx) — a goroutine without one is a leak.
- **GO-009** — Use `golang.org/x/sync/errgroup` for fan-out that cancels on first error.

## Rules — HTTP (stdlib net/http)

See [`references/http.md`](./references/http.md).

- **GO-010** — Set `ReadHeaderTimeout`/`ReadTimeout`/`WriteTimeout`/`IdleTimeout` on `http.Server`; wrap slow handlers in `http.TimeoutHandler`.
- **GO-011** — Outbound HTTP: carry context and give the client a timeout; never lean on `http.DefaultClient`'s zero timeout.
- **GO-020** — Shut down `http.Server` gracefully on SIGINT/SIGTERM via `signal.NotifyContext` + `srv.Shutdown`; treat `http.ErrServerClosed` as the clean sentinel.

## Rules — Security

See [`references/security.md`](./references/security.md).

- **GO-012** — Never build SQL by concatenation or `fmt.Sprintf` — use `database/sql` placeholders.
- **GO-013** — Escape untrusted HTML with `html/template`, never `text/template`.
- **GO-014** — Use `crypto/rand` for secrets, tokens, and password-material; `math/rand` is not a security RNG.

## Rules — Modules & dependencies

See [`references/modules.md`](./references/modules.md).

- **GO-015** — Commit `go.mod` and `go.sum`; make all changes via `go` commands, not hand-editing; run `go mod tidy`.

## Rules — Quality & tooling

See [`references/quality.md`](./references/quality.md).

- **GO-016** — Enforce `gofmt` + `go vet` over all packages in pre-commit and CI; add `staticcheck` or `golangci-lint` for deeper checks.
- **GO-019** — Scan dependencies and stdlib for known vulnerabilities in CI with `govulncheck` over all packages; call-graph reachability keeps the findings actionable.

## Rules — Testing

See [`references/testing.md`](./references/testing.md).

- **GO-017** — Table-driven tests with subtests; `t.Helper()` in test helpers; `t.Parallel()` only for truly independent cases.
- **GO-018** — Gate CI on `go test -race` over all packages; the race detector is the only tool that finds data races, and a green run is evidence, not proof.

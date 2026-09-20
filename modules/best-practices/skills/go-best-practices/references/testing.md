# GO testing rules

Detailed entries for `GO-017..GO-018`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GO-017 — Table-driven tests with subtests; `t.Helper()` in helpers; `t.Parallel()` only for independent cases

**What.** Structure tests as a table of `{name, input, want}` cases executed
under `t.Run(name, ...)` subtests. When a helper reports a test failure, mark
it `t.Helper()` so the failure points at the calling test line, not the helper
internals. Call `t.Parallel()` only where subtests share no state.

**Why.** A flat list of `if got != want` blocks can't tell you *which* case
failed, and debugging requires reading the whole function; subtests name each
case and let `go test -run 'TestParse/short'` target one. `t.Helper()` moves
failure attribution from helper internals (which are the same for every case)
to the line that called them. `t.Parallel()` speeds up independent cases but
breaks anything touching shared state — the same temp file, a shared DB, the
clock — and with `t.Run` it *reorders* execution, so cases must be genuinely
isolated before you add it.

**How.**

```go
func TestParse(t *testing.T) {
    tests := []struct {
        name, in, want string
    }{
        {"empty", "", ""},
        {"quoted", `"hi"`, "hi"},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got := Parse(tt.in)
            if got != tt.want {
                t.Fatalf("Parse(%q) = %q, want %q", tt.in, got, tt.want)
            }
        })
    }
}

func compare(t *testing.T, got, want string) {
    t.Helper()                      // failure shows the caller's line
    if got != want {
        t.Errorf("got %q, want %q", got, want)
    }
}
```

**When NOT to apply.** A single assertion or a quick reproduction doesn't need
the ceremony — but more than ~2 cases earns the table. Integration tests
sharing a real database, ports, or files should generally *not* run
`t.Parallel()` (they serialize on the shared resource). Unit tests with no
shared state should. Don't add `t.Parallel()` "for speed" to cases that read a
shared package-level variable — that's a data race, not a speedup.

---

## GO-018 — Run the race detector in CI: `go test -race ./...`

**What.** Gate CI on `go test -race ./...`, at minimum on every merge to the
default branch, alongside the GO-016 vet/staticcheck gate. `-race` builds the
test binary with the race detector instrumented in; it reports the conflicting
accesses (with both goroutine stacks) for data races that actually occur while
the tests run.

**Why.** A data race in Go isn't a benign interleaving — it's undefined
behavior. Multi-word values (interfaces, slice headers, `string`) tear into a
mix of old and new halves, and concurrent map access trips the runtime's own
check: `fatal error: concurrent map writes`, which is *not* recoverable and
takes the whole process down in production, under load, at 3am. Nothing static
catches these: `go vet` and `staticcheck` (GO-016) reason inside one goroutine,
while the two racing accesses usually live in two innocuous-looking functions
that only meet at runtime — a map cached behind a handler, a struct field a
background worker mutates (GO-008), a package-level variable a `t.Parallel()`
subtest reads (GO-017). Races also hide at laptop concurrency and appear at
production concurrency, so "it passed locally" carries no information. `-race`
is the one tool that finds them, and it finds them in the suite you already run.

**How.**

```bash
go test -race ./...    # CI gate: non-zero exit on any detected race
```

The same flag works on the other build modes when you want to drive a real
workload rather than tests: `go build -race ./cmd/server`, `go run -race .`.

**When NOT to apply.** Instrumentation is not free — per the [race detector
docs](https://go.dev/doc/articles/race_detector), memory usage may increase by
5–10x and execution time by 2–20x. A very large suite can run `-race` nightly
or over the concurrency-carrying subset (`go test -race ./internal/queue/...`)
instead of on every push — but never nowhere. It needs cgo enabled and (off
Darwin) a C compiler, and supports a fixed platform list only: linux/amd64,
linux/ppc64le, linux/arm64, linux/s390x, linux/loong64, freebsd/amd64,
netbsd/amd64, darwin/amd64, darwin/arm64, windows/amd64 — a runner on any other
target simply can't run it. Most important: the detector only finds races on
code paths that *execute*, so a green `-race` run is evidence, never proof of
race-freedom; your coverage bounds what it can possibly see.

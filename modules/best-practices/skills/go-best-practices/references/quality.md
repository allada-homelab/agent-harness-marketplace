# GO quality & tooling rules

Detailed entries for `GO-016` and `GO-019`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GO-016 — Enforce `gofmt` + `go vet ./...` in pre-commit and CI; add `staticcheck` or `golangci-lint`

**What.** `gofmt` over every file, plus `go vet ./...`, is the baseline gate
for any Go project. Add one serious static analyzer — `staticcheck`, or
`golangci-lint` (which bundles staticcheck and more) — for checks vet doesn't
cover. Run all three in pre-commit and CI, in that order.

**Why.** `gofmt` is deterministic formatting — unformatted code means every PR
carries pre-existing noise and the diff is impossible to review
line-by-line. `go vet`'s standard analyzers catch genuine bugs tests often
won't: `printf` verb mismatches, `copylocks` (copying a value that holds a
mutex), `lostcancel` (a `context.WithCancel` whose cancel is never called —
one blocking call and you leak the goroutine, GO-008), unreachable code, bad
struct tags. `staticcheck` adds a long tail (misused `errors.New`, potential
`nil` derefs, `fmt` with no args...). Enforcing in CI means the gate runs on
every merge, not one person's laptop.

**How.**

```bash
# CI / pre-commit — fail on unformatted files:
test -z "$(gofmt -l .)"
go vet ./...
staticcheck ./...
```

`go vet` needs no config. `staticcheck` reads `staticcheck.conf`; `golangci-lint` reads `.golangci.yml`.

**When NOT to apply.** `gofmt` has no meaningful exception (its output is the
canonical format). On a legacy codebase the analyzer tail can be noisy — run
`go vet` unconditionally, adopt staticcheck incrementally (disable specific
checks while triaging, then tighten), or start with golangci-lint's
default-enabled set. Generated code is normally excluded (e.g. files carrying
`// Code generated ... DO NOT EDIT.`), matching GO-015's separation of
hand-written from generated.

---

## GO-019 — Scan dependencies with `govulncheck` in CI

**What.** Run `golang.org/x/vuln/cmd/govulncheck` over the module in CI, next
to the GO-016 gate. It checks your dependency graph *and* the standard library
of the toolchain you build with against the Go vulnerability database at
`vuln.go.dev`, and exits non-zero when it finds something that reaches your
code.

**Why.** A transitive dependency that `go mod tidy` (GO-015) pulled in ships a
known CVE, and nothing in `go build`, `go vet`, or `staticcheck` notices — the
vulnerable code links into your binary silently and stays there until someone
happens to read a security bulletin. What makes govulncheck worth *gating* on,
rather than one more advisory feed, is symbol-level reachability: per
[go.dev/security/vuln](https://go.dev/security/vuln/), it "only surfaces
vulnerabilities that actually affect you, based on which functions in your code
are transitively calling vulnerable functions." Lockfile-only scanners flag
every advisory touching any version anywhere in the graph, teams learn the
output is mostly noise, and then they scroll past the one that mattered.
govulncheck's findings are dominated by code you can actually be exploited
through, so a red build carries a real signal. CI vulnerability scanning is a
convention across this library — [`python-best-practices`](../../python-best-practices/SKILL.md)
gates on `pip-audit`, [`uv-best-practices`](../../uv-best-practices/SKILL.md)
on `uv audit`; Go's equivalent is govulncheck.

**How.**

```bash
go install golang.org/x/vuln/cmd/govulncheck@latest
govulncheck ./...          # from the module root; exits non-zero on findings
```

`govulncheck -mode binary ./bin/server` scans a built artifact instead of
source. Note the exit-code carve-out: with `-format json`, `-format sarif`, or
`-format openvex` it exits 0 *regardless* of what it found — if you emit SARIF
for code scanning, keep a plain `govulncheck ./...` run as the actual gate.

**When NOT to apply.** Air-gapped or network-restricted CI can't reach the
default database; `-db` accepts an `http://`, `https://`, or `file://` URL for
any host implementing the [database spec](https://go.dev/security/vuln/database),
so mirror `vuln.go.dev/vulndb.zip` and point at it, or move the scan to a
runner that has egress — don't leave the gate silently green. Know the
documented limits before treating a clean run as a clearance: calls made
through `reflect` are invisible to static analysis, function-pointer and
interface calls are analyzed conservatively (false positives and imprecise call
stacks), binaries carry no call information so `-mode binary` can't narrow
findings the same way, and where symbol information can't be extracted it falls
back to reporting vulnerabilities for every module the binary depends on. There
is also no support for silencing a finding — an accepted risk is handled by
upgrading or by policy outside the tool.

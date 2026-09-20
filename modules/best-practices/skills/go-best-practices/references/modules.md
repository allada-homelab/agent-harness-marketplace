# GO modules rules

Detailed entries for `GO-015`. This file follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GO-015 — Commit `go.mod` and `go.sum`; make all dependency changes via `go` commands

**What.** `go.mod` (version graph and `require` directives) and `go.sum`
(expected module hashes) are source and go in the repository. Change them only
through Go commands (`go get pkg@version`, `go mod tidy`), never hand-edits.
Commit the result whenever dependencies change. `go.sum` is the supply-chain
pin: it authenticates every downloaded module hash.

**Why.** With `go.sum` committed, builds are reproducible and tamper-evident — a
swapped or re-published module version fails hash verification at download
time, and `GOPROXY` MITM is detected. If `go.mod`/`go.sum` are regenerated per
environment or refreshed casually (e.g. `go get -u ./...` inside CI), two
environments silently resolve different versions — the kind of drift that
ships untested code and only explodes in prod. Hand-edited `go.mod` diverges
from what `go mod tidy` produces, inflating review diffs and masking the real
change.

**How.**

```bash
go get github.com/google/uuid@v1.6.0     # add or pin a dependency via tooling
go mod tidy                              # reconcile go.mod/go.sum with imports
git add go.mod go.sum && git commit -m "chore: pin google/uuid v1.6.0"
```

**When NOT to apply.** Throwaway scripts that never build in CI can skip the
ceremony. For anything built by CI or shipped: commit both files — libraries and
applications alike. Since Go 1.17, module graph pruning means `go.mod` lists
direct requirements plus the indirect ones needed to build the module's own
packages and tests, so an `// indirect` block is expected in both.
Vendored code (`go mod vendor`) moves the pin into `vendor/`, but `go.mod`/
`go.sum` are still committed alongside it.

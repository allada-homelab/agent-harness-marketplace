# GO layout rules

Detailed entries for `GO-001..GO-003`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GO-001 — One Go module per repo; `go.mod` at the repo root; keep `main()` a thin wrapper

**What.** Give every repo exactly one `go.mod` at the repository root, with the
module path set to the repo's canonical import path (`module
github.com/acme/widget`). Don't create nested modules for internal packages.
In binaries, keep `main()` to two lines — construct dependencies, call a
testable `run(ctx) error`, handle the returned error.

**Why.** A single root module is the shape every Go tool assumes: `go build
./...`, `go test ./...`, vet, and linters all discover the module from the
file's position in the tree, and nested modules force `replace` directives and
surprise tooling. The `main()`/`run()` split is what makes a service testable:
`run()` can be called by tests with a real `httptest` server, while a fat
`main()` is untestable by construction.

**How.**

```go
// go.mod (repo root)
module github.com/acme/widget

go 1.24
```

```go
// cmd/server/main.go
package main

func main() {
    if err := run(context.Background()); err != nil {
        log.Fatal(err)
    }
}

func run(ctx context.Context) error {
    srv := &http.Server{Addr: ":8080", ReadHeaderTimeout: 5 * time.Second}
    // ... register routes, start background workers that stop on ctx.Done()
    return srv.ListenAndServe()
}
```

**When NOT to apply.** The standard exception is a monorepo with genuinely
distinct release cadences or teams — Go workspaces (`go.work`) give tooling a
single "module set" while keeping separate modules. If you don't need a
workspace, don't add one; one module is the default. Tiny throwaway `pkg/main`
programs can skip the `run()` ceremony, but anything with more than a handful
of lines earns it.

---

## GO-002 — Put private implementation under `internal/`

**What.** Packages that must not be imported from outside belong under an
`internal/` directory. Go enforces the boundary at compile time: code under
`internal/` is importable only by packages rooted at its parent directory.
Keep the public, importable API above `internal/`.

**Why.** Without `internal/`, "don't import this" is only a naming convention —
every package in your module (and any consumer who vendors or forks it) can
reach into the implementation. That turns a normal refactor of internals into
a public API break, and it silently grows your supported surface for zero
benefit. The compiler converts the convention into a hard, cheap boundary.

**How.**

```
acme.com/widget/
├── widget.go        # public API — clients import this package
└── internal/
    ├── store/       # importable only from acme.com/widget/ and below
    └── client/
```

**When NOT to apply.** Libraries that intentionally expose sub-packages keep
them public — `internal/` is for things that would break if someone depended
on them. `cmd/*` binaries have nobody importing them, so `internal/` buys
little there. Private repos still get value: the boundary outlives the repo
(open-source later, or another team starts consuming the package path).

---

## GO-003 — Name the package after its directory; no `util`/`common` grab-bags

**What.** A package's name is the last segment of its import path — name it
after the directory it lives in, and name the directory for what the package
*does*. Never create export-surface grab-bags called `util`, `common`,
`helpers`, or `misc`.

**Why.** Go code is read through the selector: `users.Store` tells a reader
what `Store` is because `users` narrows the noun. A `util.Wrapper(...)` call
carries no meaning and the package accumulates unrelated code — every refactor
splits its home between the grab-bag and the real destination, and new
contributors drop things in without a second thought. Cheap names make the
surface area unbounded.

**How.**

```go
// directory store/, file store.go
package store

func New(db *sql.DB) *Store { ... }
```

```go
// WRONG — a grab-bag gives readers no signal
package util

func Wrapper(s string) string { ... }
func StripHTMLTags(s string) string { ... }   // unrelated concern, parked here
```

If you can't name the package after a responsibility, split it until you can.

**When NOT to apply.** One local file with unexported helpers inside an
existing package (e.g. `stringutil.go` with only lowercase funcs) is normal
and fine — the rule targets *exported* grab-bag packages. It does not mean
every helper must become its own package; it means the package boundary should
carry meaning.

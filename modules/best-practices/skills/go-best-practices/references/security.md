# GO security rules

Detailed entries for `GO-012..GO-014`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GO-012 — Never build SQL by string concatenation or `fmt.Sprintf` — use placeholders

**What.** Parameterized queries only: `db.QueryRowContext(ctx, "SELECT ... WHERE id = ?", id)`.
The placeholder character is driver-specific — `?` for `database/sql` drivers
such as `go-sql-driver/mysql` and `mattn/go-sqlite3`, `$1`/`$2` for
`lib/pq`/`pgx` (Postgres). User-controlled values go through parameters, never
into the query text.

**Why.** Concatenated SQL plus user input is the SQL-injection vector: one
quote in the input breaks out of the string literal and executes attacker
SQL. `database/sql` sends parameter values separately from the query text on
the wire (the prepared-statement path), so it is safe by construction and also
handles quoting/escaping and type conversion correctly.

**How.**

```go
rows, err := db.QueryContext(ctx,
    "SELECT name FROM users WHERE org_id = ? AND active = ?",
    orgID, active)
```

**When NOT to apply.** Dynamic query *structure* — table names, sort columns,
`LIMIT`/`OFFSET` values — must still *not* be interpolated. Accept only
values from a closed set (whitelist against a `map[string]string` or an enum),
never raw user input. A query builder that keeps identifiers out of the value
position is acceptable; free-form string interpolation is never.

---

## GO-013 — Escape untrusted HTML with `html/template`, never `text/template`

**What.** When rendering data into HTML (a web page, an email body), use
`html/template`. It contextually autoescapes every value based on where it
appears — element text, attribute value, URL, inline script/JSON — where
`text/template` writes values verbatim.

**Why.** Untrusted data through `text/template` is stored/reflected XSS: an
attacker-controlled string like `<script>alert(document.cookie)</script>` is
shipped verbatim into the page. `html/template`'s contextual escaping is the
entire point — it escapes correctly in attributes, `style`, CSS URLs, and
inline JS, not just the `&<>` set. The two APIs look identical at the call
site, so the wrong choice is silent until someone demonstrates the XSS.

**How.**

```go
t, err := template.New("page").Parse(`<title>{{.Title}}</title><div>{{.Body}}</div>`)
if err != nil {
    return err
}
if err := t.Execute(w, Page{Title: userTitle, Body: userHTML}); err != nil {
    return err
}
```

Escaping is automatic per field and context. `template.HTML`, `template.URL`,
`template.JS` are typed opt-outs — each one is a place where you assert the
value is trusted; comment why.

**When NOT to apply.** `text/template` is correct for non-HTML output: code
generation, config files, plain-text emails, CLI help. If you render *trusted*
markup you control end-to-end (e.g. output of your own sanitizing Markdown
renderer), a typed exception around that value is acceptable — but never put
raw user content behind `template.HTML`.

---

## GO-014 — Use `crypto/rand` for secrets, tokens, and password material; `math/rand` is not a security RNG

**What.** Security-sensitive randomness — API keys, session tokens, password
salts, password-reset codes, unguessable IDs — comes from `crypto/rand`
(`crypto/rand.Read` or `crypto/rand.Int(rand.Reader, max)`). `math/rand` (and
`math/rand/v2`) is a deterministic PRNG for simulation and tests; anything an
attacker can observe or predict must not come from it.

**Why.** `math/rand`'s generator state is recoverable from its output and each
process is seeded from a small value, so two services starting at the same wall
clock can mint identical "unique" IDs, and values are predictable to someone
observing a few outputs. A token an attacker can predict defeats auth, reset,
and CSRF protection — the class of bug behind real account-takeover incidents.
`crypto/rand` produces values that are not feasibly distinguishable from
uniform randomness.

**How.**

```go
b := make([]byte, 32)
if _, err := rand.Read(b); err != nil {
    return err        // crypto/rand can fail (entropy unavailable)
}
token := base64.RawURLEncoding.EncodeToString(b)   // URL-safe, no padding
```

Prefer `crypto/rand.Int` when you need a range without modulo bias.

**When NOT to apply.** Simulations, games, tests, and benchmarking want
deterministic or fast randomness — `math/rand`/`math/rand/v2` is the right
tool there (and a *seeded* `rand.New(rand.NewSource(...))` is a feature for
reproducible tests, not a bug). The moment a value becomes a security boundary
— login tokens, password-reset links, CSRF tokens, unguessable UUIDs,
encryption keys — it must come from `crypto/rand`.

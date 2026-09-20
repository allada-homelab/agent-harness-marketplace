# UVP lockfile rules

Detailed entries for `UVP-010..UVP-019`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the [uv sync docs](https://docs.astral.sh/uv/concepts/projects/sync/)
and the [uv CLI reference](https://docs.astral.sh/uv/reference/cli/).
The lockfile format itself is documented in
[uv concepts: projects/layout](https://docs.astral.sh/uv/concepts/projects/layout/).

---

## UVP-010 — Commit `uv.lock` for **both** apps and libraries

**What.** Check `uv.lock` into version control regardless of whether
the project is an app you deploy or a library you publish. The uv
docs are unambiguous: "it should be checked into version control,
allowing for consistent and reproducible installations across
machines."

**Why.** Two failure modes from skipping it:

1. **Non-reproducible CI / dev environments.** Without `uv.lock`, every fresh `uv sync` re-resolves against the current state of PyPI. The version you tested locally on Monday and the version CI installs on Wednesday can differ — possibly across a breaking change in a transitive. The bug shows up in CI for "no reason" and is impossible to bisect against the project's own history.
2. **Bisecting bugs becomes impossible.** When `git bisect` finds a regression, you want to install *that exact commit's dependencies* to confirm. No lockfile, no time travel.

The (out-of-date) advice that "libraries shouldn't commit lockfiles"
applies to *what gets published to PyPI* — the lockfile doesn't go
in the wheel and consumers resolve freely. But the *repo itself* is
where your CI, your tests, and your contributors live; they all need
the lockfile.

**How.**

```bash
# Typical workflow on first project setup
uv init --lib mylib
cd mylib
uv add httpx pydantic
uv add --dev pytest ruff mypy
# uv.lock is created automatically — commit it
git add pyproject.toml uv.lock
git commit -m "Initialize project"
```

Then ensure `uv.lock` is *not* in `.gitignore`:

```
# .gitignore — do NOT ignore uv.lock
.venv/
__pycache__/
*.pyc
.pytest_cache/
# uv.lock     <-- this line is wrong; remove it
```

**When NOT to apply.** Never. Even libraries should commit the
lockfile. The cost of having it is zero; the cost of not having it
is real reproducibility loss.

---

## UVP-011 — `--locked` validates lock vs `pyproject.toml`; `--frozen` skips validation AND skips installing the project package

**What.** Two superficially-similar flags with importantly different
semantics:

- **`uv sync --locked`** — Reads `uv.lock`. *Validates* that the lockfile is up-to-date with `pyproject.toml`. **Errors if not.** Builds and installs the project package along with deps.
- **`uv sync --frozen`** — Reads `uv.lock`. *Skips* the lock-vs-pyproject check. Also **skips installing the project package itself** — only deps are installed.

They aren't interchangeable. Pick by intent.

**Why.** Three real-world failure modes from confusing them:

1. **Using `--frozen` in CI hides stale lockfiles.** A PR that modifies `pyproject.toml` (adds a dep, tightens a constraint) but forgets to run `uv lock` produces an out-of-date `uv.lock`. With `--frozen`, CI happily proceeds with the *old* lockfile — tests pass, the PR merges, and production silently installs different versions than what was reviewed.
2. **Switching from `--frozen` to `--locked` in Docker triggers project install.** A Dockerfile that used `--frozen` (installing only deps in a layer, copying source after) suddenly tries to build the project when switched to `--locked`. If the project has a non-trivial build (maturin, hatch-fancy-pypi-readme, etc.), the build can fail or pull in toolchain you didn't include in that layer ([uv#9379](https://github.com/astral-sh/uv/issues/9379)).
3. **`--frozen --group <name>` used to swallow typos silently.** Before uv 0.6.0, `uv sync --frozen --group does-not-exist` succeeded with no warning — the group name was silently ignored against the frozen lockfile. uv 0.6.0 changed this so that `--frozen` still validates that requested groups exist in the lockfile, surfacing the typo. If you're on a pre-0.6.0 uv, a misspelled group is invisible; pin a newer uv via `[tool.uv] required-version` (UVP-008) to get the loud failure.

The asymmetry is critical: `--locked` does *more* than `--frozen`
(check + install project); `--frozen` is not "`--locked` minus the
check."

**How.**

```bash
# CI — enforce lockfile is current, install everything
uv sync --locked

# Production Docker — lockfile already validated upstream, fast install only
uv sync --frozen --no-dev --no-editable

# Local dev — usually no flag (auto-locks); --locked if you want loud failure
uv sync
```

A common Dockerfile pattern that uses both:

```dockerfile
# Layer 1: deps only, fast cache reuse
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Layer 2: project itself, busts when source changes
COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable
```

(See `containers-best-practices/references/uv-python.md` `UV-002`
for the two-pass Docker sync in detail.)

**When NOT to apply.** Local interactive development is one place
bare `uv sync` (no flag) is acceptable — it auto-syncs the lockfile
when `pyproject.toml` changes, which is what you want when iterating.
CI and Docker should always pick one of `--locked` / `--frozen`
explicitly.

---

## UVP-012 — Use targeted `uv lock --upgrade-package <name>` over blanket `uv lock --upgrade`

**What.** When updating dependencies, prefer:

```bash
uv lock --upgrade-package requests          # only requests + its transitives
uv lock --upgrade-package "requests>=2.32"  # bump and tighten in one shot
```

over:

```bash
uv lock --upgrade                            # everything
```

The blanket form is correct for scheduled refreshes (e.g. weekly
Dependabot-equivalent). The targeted form is correct for everyday
"I need to update X" workflows.

**Why.** Blanket `--upgrade` re-resolves every dependency, including
transitives, against latest constraints. Three failure modes:

1. **Surprise breaking changes.** An unrelated dep silently jumps a major version because nothing was holding it back. The PR diff is enormous; reviewers can't tell what's intentional vs incidental.
2. **Hard-to-bisect production regressions.** When a regression ships, "which dep change caused it?" is unanswerable when 47 packages changed in one PR. Targeted upgrades produce small auditable diffs.
3. **Defeats Renovate / Dependabot intent.** Those tools open one PR per dep update for exactly this reason — to keep the review surface small. Running `uv lock --upgrade` by hand on every refresh undoes that property.

**How.**

```bash
# Day-to-day: update one thing
uv lock --upgrade-package fastapi
git add uv.lock
git commit -m "Bump fastapi to latest"

# Bump and tighten the floor at the same time
uv add 'fastapi>=0.110'   # updates pyproject + lock

# Scheduled refresh — accept all updates that pass tests
uv lock --upgrade
# review the diff in PR; reviewers should be the deps team, not feature reviewers
```

Important: the lockfile is **not** invalidated by upstream releases.
Running `uv sync --locked` doesn't auto-discover newer versions. You
explicitly choose when to refresh.

**When NOT to apply.** Initial scaffolding of a project, where the
lockfile is empty and the first `uv lock` legitimately resolves
everything. After that, targeted is the default.

---

## UVP-013 — Never manually edit `uv.lock` — it's fully generated

**What.** Treat `uv.lock` as machine-generated. Don't open it in an
editor to "just tweak a version" or "remove a transitive you don't
want."

**Why.** Three failure modes:

1. **Hash mismatches.** Each lockfile entry includes content hashes. Editing a version string without updating the hash causes `uv sync` to fail with "hash verification failed" — or worse, with some package managers, silently install the old version because the hash doesn't match the new one.
2. **Dependency-graph inconsistency.** The lockfile encodes the *resolved* dependency graph — which version of A satisfies B's constraint, which version of B was picked given C's. Editing one entry doesn't update the others; the graph becomes internally inconsistent.
3. **uv silently regenerates.** When uv detects tampering it can't recover from, it regenerates the lockfile from `pyproject.toml`. Your edit vanishes without an obvious error message.

If you need a specific transitive version pinned, do it correctly in
`pyproject.toml`:

**How.**

```toml
# pyproject.toml — pin via constraint, not via lockfile edit
[project]
dependencies = [
  "fastapi",
  "pydantic>=2.5,<2.6",      # pinning pydantic explicitly
]

# alternative: use uv's resolver overrides for transitive pins
[tool.uv]
override-dependencies = [
  "starlette==0.36.3",        # force a specific version
]
```

Then `uv lock` to regenerate. The lockfile is always derived; the
project file is always the source of truth.

**When NOT to apply.** Never. There's no legitimate reason to hand-edit
`uv.lock`. If you think there is, the right answer is in
`pyproject.toml` or `[tool.uv]` overrides.

---

## UVP-014 — Don't commit `requirements.txt` alongside `uv.lock`

**What.** Pick one source of truth. If your toolchain is uv, the
lockfile is `uv.lock`. Don't *also* commit a `requirements.txt` that
duplicates it.

**Why.** Two sources of truth drift. Concrete failure modes:

1. **Deploy uses stale requirements.** A common pattern is "we use uv locally but our deploy pipeline reads requirements.txt." When someone updates `pyproject.toml` and `uv.lock` but forgets to regenerate `requirements.txt`, deploys silently install old versions.
2. **The two files disagree about extras / dev deps.** The published requirements often doesn't include dev groups; over time it drifts further from what the lockfile actually represents.

uv's own docs say: "In general, we recommend against using both a
`uv.lock` and a `requirements.txt` file."
([uv export docs](https://docs.astral.sh/uv/concepts/projects/export/))

**How.** If a downstream tool genuinely requires `requirements.txt`
(some Lambda deployment paths, certain Terraform providers), generate
it in CI as a build artifact:

```yaml
# .github/workflows/build.yml
- name: Export requirements.txt for deploy
  run: |
    uv export --format requirements.txt \
      --no-hashes --no-dev --no-emit-project \
      -o requirements.txt
    # use requirements.txt for the deploy step — don't commit it
- name: Deploy
  run: |
    aws lambda update-function-code ...
```

If you *must* commit `requirements.txt` (some CI gate insists), then
generate it in a pre-commit hook and have CI verify the committed
version matches a freshly-generated one:

```bash
# CI check
uv export --format requirements.txt --no-hashes --no-dev -o /tmp/requirements.txt
diff requirements.txt /tmp/requirements.txt || \
  { echo "requirements.txt is stale; run 'uv export'"; exit 1; }
```

The newer `pylock.toml` format (PEP 751) is also supported via `uv
export --format pylock.toml` and is preferred over requirements.txt
when downstream tools support it — same "generate, don't commit"
rule applies.

**When NOT to apply.** Pure interop scripts that need a one-shot
requirements.txt — generate, use, throw away. The rule is about
*committed* requirements.txt alongside the lockfile.

---

## UVP-015 — `uv lock --check` and `uv sync --check` validate different things; compose, don't substitute

**What.** Two superficially-similar `--check` flags with **different
scopes**:

- **`uv lock --check`** — validates that `uv.lock` is up-to-date with respect to `pyproject.toml`. Does not touch the environment. Exits non-zero if the lockfile is stale. (Equivalent to the older `--locked` form of `uv lock`.)
- **`uv sync --check`** — added in uv 0.6.10. Validates that the **installed environment** matches `uv.lock`. Does not modify the environment. Exits non-zero if a package in the venv differs from the lockfile.

They're composable, not interchangeable: `lock --check` covers
"pyproject ↔ lockfile" drift, `sync --check` covers "lockfile ↔ venv"
drift. Use both at the gates that matter.

**Exit code (changed in 0.8.0):** a failed `--check` now exits with code
**1** — it was **2** in earlier uv. Any CI gate or script that branches
on `[ $? -eq 2 ]` to detect drift will silently treat a real failure as
success after the upgrade. Test for non-zero, not for `2`.

**Why.** Confusing the two leads to false-confidence CI:

1. **`sync --check` alone misses missing `uv lock` runs.** A PR adds a dep to `pyproject.toml` and forgets `uv lock`. The committed `uv.lock` is stale; the venv built from it doesn't match `pyproject.toml`'s intent. `uv sync --check` happily says "venv matches lockfile" — it does — and the stale lockfile sails through.
2. **`lock --check` alone misses environment drift.** A CI cache restores a stale `.venv` (against UVP-031's advice but it happens). The lockfile is current; the venv is not. `uv lock --check` passes; tests run against the wrong versions.

The CI shape that catches both is `uv lock --check` as a **pre-gate**
before any install work, then `uv sync --locked` to install. The
`--locked` flag on `sync` is the "do it" form; `--check` is the
"verify, don't do it" form. Both exist for a reason.

**How.**

```yaml
# .github/workflows/test.yml
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>
      - uses: astral-sh/setup-uv@<sha> # v8.1.0
        with:
          enable-cache: true

      # Pre-gate: lockfile is current w.r.t. pyproject.toml
      - name: Verify lockfile
        run: uv lock --check

      # Install from the lockfile, refuse if it's stale
      - run: uv sync --locked --dev

      # Optional: verify the installed env actually matches the lock
      # (mostly useful when caching .venv against UVP-031)
      - name: Verify environment matches lockfile
        run: uv sync --check
```

Common mistake: treating `uv sync --locked` and `uv sync --check` as
the same check. `--locked` *installs* (refusing on stale lockfile);
`--check` *only verifies* (refusing on env drift). One is the gate,
the other is the diagnostic.

**When NOT to apply.** Local dev shells where `uv sync` auto-relocks
on pyproject changes — neither `--check` flag is what you want there
(you want the auto-relock). The rule is for CI and other strict
gates.

---

## UVP-070 — Use `uv lock --upgrade-group <group>` to refresh one group in isolation

**What.** `uv lock --upgrade-group <group>` (added in uv 0.11.4) upgrades
every package in one dependency group to its latest compatible version
without touching packages in other groups — more targeted than
`--upgrade` (everything) and less tedious than chaining
`--upgrade-package` per tool.

**Why.** "Refresh just the linting/test tools" previously meant either
`uv lock --upgrade` (too broad — it bumps production deps in the same
sweep, mixing risk levels in one diff) or a string of
`--upgrade-package ruff --upgrade-package mypy ...`. `--upgrade-group dev`
is the right surgical scope: dev-tooling churn stays out of the
production-dependency diff.

**How.**

```bash
uv lock --upgrade-group dev      # bump all dev deps, leave prod alone
uv lock --upgrade-group test
```

**When NOT to apply.** Production dependency bumps — use targeted
`uv lock --upgrade-package <name>` (UVP-012) for an explicit, reviewable
change, or a full `uv lock --upgrade` in a scheduled, reviewed PR.
`--upgrade-group` is primarily for dev/test maintenance.

---

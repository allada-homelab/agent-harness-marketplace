# UVP python-versions rules

Detailed entries for `UVP-050..UVP-054`. Covers the
`.python-version` vs `requires-python` distinction, patch-vs-minor
pinning, disabling Python downloads in network-restricted CI, the
`uv version` (project) vs `uv self version` (binary) split as of
0.7.0, and resolution-strategy matrix testing for libraries.

Citations point at the
[uv Python versions docs](https://docs.astral.sh/uv/concepts/python-versions/).

For Dockerfile-side Python handling (system Python vs uv-managed,
`UV_PROJECT_ENVIRONMENT=/usr/local`), see the container plugin's
`UV-007` rule.

---

## UVP-050 — `.python-version` pins the runtime; `requires-python` declares the compat floor

**What.** Two superficially-similar configuration points that mean
different things:

| File / field | Scope | Purpose |
|---|---|---|
| `.python-version` (file in repo) | Local + CI runtime selection | Pins which interpreter uv runs against |
| `[project] requires-python` (pyproject.toml) | Project metadata | Declares which Python versions the project *supports* |

`.python-version` says "use this Python for development."
`requires-python` says "this package is compatible with this Python."
They look similar; they aren't.

**Why.** Conflating them causes loud and quiet failures:

1. **Setting only `requires-python = ">=3.12"` doesn't pin CI to 3.12.** CI will use whatever Python is active in the runner (often a system default like 3.10) unless `.python-version`, `UV_PYTHON`, or the `setup-uv` action's `python-version` input also specifies. Result: "tests pass locally, fail in CI" because the Python versions differ even though `requires-python` matched both.
2. **Setting only `.python-version = "3.12"` doesn't tell downstream consumers anything.** A library published to PyPI without `requires-python` is offered to users on every Python version. Users on 3.9 install it, hit syntax errors at import time, and file confusing bug reports.
3. **The "pin everywhere" mental model is wrong.** Locking `requires-python` to a single version (`==3.12`) blocks consumers on newer Pythons (see UVP-003). The right shape is: floor in `requires-python`, exact pin in `.python-version`.

**How.**

```
.python-version       # pin for local + CI
3.12
```

```toml
# pyproject.toml — floor for consumers
[project]
name = "myapp"
requires-python = ">=3.12"
```

```bash
# refresh .python-version via uv (validates the version exists)
uv python pin 3.12
# this writes "3.12" to .python-version
```

In CI, either `.python-version` is picked up automatically by
`setup-uv`, or you specify explicitly:

```yaml
- uses: astral-sh/setup-uv@<sha> # v8.1.0
  with:
    python-version: "3.12"        # overrides .python-version if needed
    enable-cache: true
```

For a matrix across multiple Python versions, the matrix var
overrides `.python-version`:

```yaml
strategy:
  matrix:
    python-version: ["3.11", "3.12", "3.13"]
```

**When NOT to apply.** Single-file scripts using PEP 723 inline
metadata — those don't have a `.python-version` and instead declare
`# /// script\n# requires-python = ">=3.12"\n# ///` in the file
itself. Different mechanism, same idea.

---

## UVP-051 — Pin the *minor* version in `.python-version` (`3.12`), not the *patch* (`3.12.7`)

**What.** Write `3.12` in `.python-version`, not `3.12.7`. uv will
auto-select a patch release within the pinned minor.

**Why.** Two opposite failures from the wrong pinning level:

1. **Pinning the patch (`3.12.7`)** — every security release of CPython (which happen monthly) leaves your project on an older, vulnerable Python until someone manually bumps `.python-version`. The pin is *too tight*; you've opted out of free security updates.
2. **Pinning the major only (`3`)** — uv could legitimately pick Python 3.10 or 3.14. Resolution differs across minors (different stdlib, different syntax support); your lockfile becomes ambiguous. The pin is *too loose*.

Pinning the minor (`3.12`) is the sweet spot: patch upgrades flow
in transparently (which uv's docs explicitly support: "uv does not
allow transparently upgrading across minor Python versions...
Patch upgrades are transparent."), and the resolution stays
stable across patches.

**How.**

```
.python-version
3.12                                 # good — minor pin
```

```
.python-version
3.12.7                               # bad — too tight, freezes security
```

```
.python-version
cpython-3.12.7-linux-x86_64-gnu      # bad — platform-specific, breaks on macOS
```

For exact reproducibility (e.g. in deploys where you genuinely
need the patch pinned), do it via `uv lock`'s Python version
constraint or via your deploy infrastructure (Docker base image
pinned to `python:3.12.7-slim@sha256:...`), not via `.python-version`.

**When NOT to apply.** Two cases:

1. **Pre-release Python testing.** When testing against `3.14.0rc1`, you may need the full version string to disambiguate from `3.14.0rc2`. Use the full string, then drop back to `3.14` once it ships stable.
2. **Compliance-driven pinning.** Some regulated environments require exact patch pinning for traceability. Do it in deploy config (`Dockerfile`, infra-as-code), not in `.python-version`.

---

## UVP-052 — `UV_PYTHON_DOWNLOADS=never` in network-restricted CI

**What.** In CI environments without (or with restricted) network
access to download Python builds, set:

```bash
export UV_PYTHON_DOWNLOADS=never
```

or in `pyproject.toml` / `uv.toml`:

```toml
[tool.uv]
python-downloads = "never"
```

**Why.** By default, uv will *automatically download* a managed
Python build from the
[python-build-standalone](https://github.com/astral-sh/python-build-standalone)
project if the required version isn't found locally. In environments
where this network call fails — locked-down CI, air-gapped systems,
corporate proxies that intercept HTTPS — the failure mode is a
confusing network error rather than a clean "Python not found":

```
error: Failed to download cpython-3.12.7-linux-x86_64-gnu.tar.gz
  Caused by: error sending request for url
  Caused by: error trying to connect: tcp connect error: Connection refused
```

The actual problem ("we don't have Python 3.12 installed and we
can't download it") is buried under network noise. Worse, the build
can hang on retries.

With `UV_PYTHON_DOWNLOADS=never`, the same situation produces:

```
error: No interpreter found for Python 3.12 in managed installations or search path
```

— which is clear, actionable, and points at the actual fix
(provision Python via the system or `setup-uv`'s `python-version`
input, instead of expecting uv to fetch it).

**How.**

```yaml
# GitHub Actions in a restricted environment
env:
  UV_PYTHON_DOWNLOADS: "never"
jobs:
  test:
    runs-on: self-hosted-restricted
    steps:
      - uses: astral-sh/setup-uv@<sha> # v8.1.0
        with:
          python-version: "3.12"        # setup-uv handles Python provisioning
      - run: uv sync --locked
      - run: uv run pytest
```

```dockerfile
# Dockerfile in air-gapped build environment
FROM python:3.12-slim
ENV UV_PYTHON_DOWNLOADS=never
COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev          # uses the base image's Python; no download attempt
```

Pair with `[[tool.uv.index]]` if your CI also can't reach PyPI:

```toml
[tool.uv]
python-downloads = "never"

[[tool.uv.index]]
name = "internal"
url = "https://pypi.corp.example/simple"
default = true
```

**When NOT to apply.** Standard GitHub-hosted runners with unrestricted
network access — let uv (or `setup-uv`) auto-provision Python. The
rule applies to *restricted* CI environments specifically.

---

## UVP-053 — `uv version` manages the project version (uv 0.7+); use `uv self version` for the binary

**What.** As of uv 0.7.0, `uv version` reports and modifies the
**project's** version field in `pyproject.toml`. The previous
behavior — printing the uv binary's own version — moved to
`uv self version`. Since uv 0.8.0, running `uv version` *outside* a
project is a **hard error** — the 0.7.x fallback (print the binary
version with a deprecation warning) was removed, so any script that
relied on it now fails outright rather than misbehaving quietly.

```bash
uv version                       # prints project version (e.g. "0.3.4")
uv version 1.0.0                 # sets project version to 1.0.0
uv version --bump patch          # 0.3.4 → 0.3.5
uv version --bump minor          # 0.3.4 → 0.4.0
uv version --bump major          # 0.3.4 → 1.0.0

uv self version                  # prints uv binary version
uv self update                   # updates the binary
```

**Why.** Pre-0.7 scripts, Makefiles, and CI steps that used
`uv version` to print or assert the uv binary version silently broke
on the upgrade. The command kept working but started producing the
*project* version instead — same exit code, different output. Two
real failure modes:

1. **CI version-gate breaks silently.** A script that did `[[ "$(uv version)" =~ "0.5" ]] || exit 1` (intended to verify uv ≥ 0.5) now compares against the project's version, almost certainly passing or failing for the wrong reason. The gate provides false confidence.
2. **Makefile / release scripts overwrite the project version.** A Makefile snippet `uv version > VERSION` previously wrote the uv binary version into a `VERSION` file. After 0.7 it writes the *project* version — same command, completely different semantics. If the project version was already what you wanted in `VERSION`, the bug is invisible until you upgrade uv across releases and notice the file stopped updating.

The fix is two-fold:
- Replace any "check uv binary" usage with `uv self version`.
- Pin a uv floor via `[tool.uv] required-version = ">=0.7.0"` (UVP-008) so the meaning of `uv version` is unambiguous for everyone who touches the project.

**How.**

```bash
# release workflow — bump the project version, tag, build, publish
uv version --bump minor          # writes new version to pyproject.toml
new_version="$(uv version --short)"
git add pyproject.toml
git commit -m "Release v${new_version}"
git tag "v${new_version}"
uv build
uv publish

# verify the uv binary is recent enough (CI guard)
uv self version                  # e.g. "uv 0.7.19"
```

For projects on `[tool.uv] dynamic-version`, `uv version` reads from
the dynamic source (e.g. setuptools-scm git tag) — setting via
`uv version 1.0.0` errors with a clear "this project uses dynamic
versioning" message.

**When NOT to apply.** Two cases:

1. **Pre-0.7 uv binaries**, where `uv version` is still the binary version. Those installs should upgrade; until then, treat `uv version` as the binary command and use a different mechanism (read `pyproject.toml`) for the project version.
2. **Dynamic version projects.** Where the version is computed from git or another source, `uv version --bump` doesn't apply; bump the source (the tag, the file) instead.

---

## UVP-054 — Resolution strategy for libraries: matrix-test `lowest-direct` and `highest`

**What.** Libraries (published to PyPI) need to test against the
**floor** of their declared dependency ranges, not just the latest
versions. uv exposes `--resolution` to control which versions the
resolver picks; matrix the two ends in CI:

```bash
# lowest-direct: pin direct deps to their declared minimums; transitives latest-compatible
uv lock --resolution lowest-direct
uv sync --locked && uv run pytest

# highest (default): everything at latest compatible
uv lock --resolution highest
uv sync --locked && uv run pytest
```

`lowest-direct` catches "we said `>=2.4` but actually require a 2.5
feature." `highest` (the default) catches "an upper-bound on a dep
just expired and a new major broke us."

See the [uv resolution docs](https://docs.astral.sh/uv/concepts/resolution/#resolution-strategy).

**Why.** Two distinct classes of bug, both invisible without the matrix:

1. **Implicit floor violations.** A library declares `pandas>=2.0` because that's what the maintainer happened to have installed. Six months later someone reports "`pandas==2.0.3` users get `AttributeError`" — the code actually used a method added in 2.1. `lowest-direct` would have caught this at the first CI run.
2. **Upper-bound rot.** Users on the latest Python or latest dep version hit a regression nobody's environment caught because dev / CI was always on the "happy path" middle version. `highest` (default) pulls latest, surfacing the regression in the library's own CI before users see it.

`fork-strategy` is the companion control for wide `requires-python`
ranges:

- `fork-strategy = "fewest"` — produces the smallest lockfile, picking versions compatible with the *whole* `requires-python` range. Best for libraries that want a single coherent dependency set.
- `fork-strategy = "requires-python"` (default) — picks the latest compatible version *per Python version fork*. Best when newer Python versions can use newer deps that older Pythons can't.

**How.**

```yaml
# .github/workflows/test.yml
strategy:
  fail-fast: false
  matrix:
    python-version: ["3.12", "3.13"]
    resolution: ["highest", "lowest-direct"]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>
      - uses: astral-sh/setup-uv@<sha> # v8.1.0
        with:
          python-version: ${{ matrix.python-version }}
          enable-cache: true
      - name: Resolve at ${{ matrix.resolution }}
        run: uv lock --resolution ${{ matrix.resolution }}
      - run: uv sync --locked
      - run: uv run pytest
```

For libraries supporting a wide Python range, set `fork-strategy` in
`pyproject.toml`:

```toml
[tool.uv]
fork-strategy = "fewest"         # minimize lockfile bloat for >=3.9 ... <3.14
```

**When NOT to apply.** Applications (not libraries) — apps install
from the committed lockfile, so the floor doesn't matter; what
matters is "what does the lockfile resolve to right now." For apps,
test against the lockfile only. The matrix is library-specific.

---

## UVP-067 — Keep managed interpreters patched with `uv python upgrade`

**What.** `uv python upgrade` (stable since uv 0.10.0) upgrades a managed
CPython install to the latest patch within its minor version and
**auto-upgrades any virtual environments** pointing at the old patch.

**Why.** A managed Python installed on first `uv python install`/`pin`
stays at whatever patch was current then. CPython security fixes ship in
patch releases (3.12.5 → 3.12.6 for a CVE), so without upgrading, a
developer machine silently runs a vulnerable interpreter. The
upgrade-plus-venv-auto-upgrade makes it one command instead of a manual
reinstall-and-recreate.

**How.**

```bash
uv python upgrade 3.12     # bump 3.12.x to the latest 3.12 patch
uv python upgrade          # all managed versions
```

**When NOT to apply.** System Python (not uv-managed) — `uv python
upgrade` doesn't touch it. Compliance environments that must control the
exact installed patch should manage the installer separately and set
`UV_PYTHON_DOWNLOADS=never` (UVP-052).

---

## UVP-073 — uv's default managed Python is 3.14 since 0.9.0 — pin explicitly

**What.** Since uv 0.9.0 (Oct 2025), uv's default managed Python is
**3.14** (previously 3.13). A project initialized without a
`.python-version`, on a machine with no pinned managed Python, gets 3.14.
Free-threaded 3.14 (`3.14t`) no longer requires an explicit opt-in flag.

**Why.** This is a behavioral default change: a repo without
`.python-version` that *implicitly* relied on 3.13 now silently gets 3.14
on a fresh machine running uv ≥0.9. Libraries not yet tested against 3.14
can surface new syntax warnings, deprecation behavior (e.g. deferred
annotations), or compatibility breaks — at `uv run` time, not when you
chose to upgrade.

**How.** Anchor the runtime explicitly rather than inheriting the moving
default:

```bash
uv python pin 3.12        # immune to uv's default-version changes
```

Projects that *want* 3.14 should pin it too, so every contributor and CI
agree on the minor.

**When NOT to apply.** A project that deliberately tracks uv's latest
stable default and accepts the churn — leave it unpinned, and document
the choice in CONTRIBUTING so it's intentional, not accidental.

---

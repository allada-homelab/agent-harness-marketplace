# UVP environments & sync rules

Detailed entries for `UVP-020..UVP-025`. Covers production sync
patterns, `uv run` vs venv activation, `UV_PROJECT_ENVIRONMENT`,
`default-groups` configuration, PEP 723 inline scripts, and named
indexes via `[[tool.uv.index]]`.

Citations point at the [uv sync docs](https://docs.astral.sh/uv/concepts/projects/sync/)
and the [uv project config docs](https://docs.astral.sh/uv/concepts/projects/config/).

---

## UVP-020 — Production sync incantation: `uv sync --locked --no-dev --no-editable`

**What.** The canonical production install command is:

```bash
uv sync --locked --no-dev --no-editable
```

Each flag closes a specific failure mode. They're not optional
together.

**Why.** Three separate failures, one per flag:

1. **Without `--locked`** — bare `uv sync` happily updates the lockfile if `pyproject.toml` has drifted. In production, that means the install can pick up versions different from what was reviewed in the PR / tested in CI. `--locked` enforces "use the committed lockfile, fail loudly if it's stale."
2. **Without `--no-dev`** — pytest, ruff, mypy, and any other dev-group deps ship into the production image. Bloat at best; an attack surface at worst (dev tools often have privileged paths and broad permissions).
3. **Without `--no-editable`** — the project itself is installed as an editable link pointing into the build context. In a Docker build, this works during the build (source is present), but in the final image when source is `COPY`'d via a different path or stripped, `import myapp` either fails or picks up a stale copy. `--no-editable` installs a real wheel that doesn't depend on the source tree's location.

**How.**

```dockerfile
# Dockerfile — production stage
WORKDIR /app
COPY pyproject.toml uv.lock ./

# layer 1: deps only, cache-friendly
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/

# layer 2: project itself, no editable link
RUN uv sync --frozen --no-dev --no-editable
```

(Note: `--frozen` here, not `--locked` — the lockfile was already
validated upstream in CI. See UVP-011.)

Outside Docker — generic deploy:

```bash
# fail loudly if lockfile is stale; install only prod deps; not editable
uv sync --locked --no-dev --no-editable
```

If you have additional groups beyond `dev` that shouldn't ship in
production (test, docs), exclude them too. `--no-default-groups` is
the broad hammer; per-group with `--no-group <name>` is surgical:

```bash
uv sync --locked --no-default-groups --no-editable
# or
uv sync --locked --no-group dev --no-group test --no-group docs --no-editable
```

**When NOT to apply.** Dev images that *want* the editable install
(so source changes show up without re-syncing) — omit `--no-editable`.
Dev images that need pytest available — omit `--no-dev`. The full
incantation is for *production*; pick the subset that matches your
stage.

---

## UVP-021 — `uv run` over manual `.venv/bin/activate`

**What.** When running project commands (in CI, scripts, Makefiles,
anywhere), prefer:

```bash
uv run pytest
uv run python -m myapp
uv run my-cli-entry-point
```

over:

```bash
source .venv/bin/activate
pytest
```

**Why.** `uv run` does three things `source activate` doesn't:

1. **Re-checks the lockfile before executing.** If `pyproject.toml` changed since the last sync, `uv run` syncs first (or errors if `--locked` is set). Activation gives you whatever environment exists, which may be stale.
2. **Doesn't pollute the shell.** Activation modifies `PATH`, `VIRTUAL_ENV`, and your prompt for the rest of the session. `uv run` is per-invocation and leaves no trace, which is critical in CI where the next step might be sensitive to env-var pollution.
3. **Works without a shell.** Scripts that need to invoke project commands from non-shell contexts (Make, Just, GitHub Actions `run:` steps that run via a fresh shell each step) can't easily `source` something. `uv run` is one command.

There's also a performance angle: `uv run --no-sync` skips the lock
check entirely for hot inner loops (e.g. inside a test that spawns
subprocesses). Use this when you've just synced and don't want to
pay the verification cost on every invocation.

**How.**

```yaml
# GitHub Actions
- name: Test
  run: uv run pytest                          # good

# vs
- name: Test
  run: |
    source .venv/bin/activate                 # bad: env-var pollution,
    pytest                                     #      and no lock check
```

```makefile
# Makefile
.PHONY: test
test:
	uv run pytest

.PHONY: lint
lint:
	uv run ruff check .
	uv run mypy src/
```

For an *interactive* shell where you genuinely want activation
(debugging, exploration), `source .venv/bin/activate` is fine — but
`uv sync` first to make sure it's current.

**When NOT to apply.** Two cases:

1. **Persistent interactive sessions** where you'd rather `python` works without prefix. Activate consciously and remember to sync first.
2. **Performance-critical hot loops** where the sync check is measurable overhead. Use `uv run --no-sync` after a known-good sync.

---

## UVP-022 — Set `UV_PROJECT_ENVIRONMENT` only to absolute paths

**What.** `UV_PROJECT_ENVIRONMENT` redirects where uv creates and
syncs the project venv. When you need this — Docker, custom CI
layouts, anything that doesn't want `.venv/` at the project root —
use an **absolute** path.

```bash
# good — absolute path, unambiguous
export UV_PROJECT_ENVIRONMENT=/app/.venv

# bad — relative path
export UV_PROJECT_ENVIRONMENT=.venv-special
```

**Why.** Relative paths resolve relative to the *current working
directory*, not the project root. In a multi-project repo or a
script that `cd`s between directories, this is a silent disaster:

- `uv sync` in `packages/a` creates `packages/a/.venv-special`
- `uv sync` in `packages/b` creates `packages/b/.venv-special`
- A third invocation from the repo root creates `.venv-special` at the root

— and tools downstream that expect one path get whichever one ran
last. Worse, if the relative path resolves to a *system* prefix
(`/usr/local`), uv's "remove extraneous packages by default"
behavior will start deleting from the system Python. The docs
explicitly warn: "Using `uv sync` on system environments is risky,
as it removes extraneous packages by default and may leave the
system broken." ([config docs](https://docs.astral.sh/uv/concepts/projects/config/#project-environment-path))

**How.**

```dockerfile
# Dockerfile — pin the absolute venv path
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
```

```bash
# CI step that runs across multiple projects
for proj in packages/*; do
  pushd "$proj"
  UV_PROJECT_ENVIRONMENT="$(pwd)/.venv" uv sync --locked
  popd
done
```

**When NOT to apply.** Don't set `UV_PROJECT_ENVIRONMENT` at all if
you're happy with the default `.venv/` next to `pyproject.toml`.
The variable exists for non-default layouts; setting it
unnecessarily is just one more thing that can go wrong.

A separate note on `VIRTUAL_ENV`: uv **ignores** `VIRTUAL_ENV`
during project operations by default. If you activated a custom
venv via `source .../activate` and then run `uv add foo`, uv creates
a *second* `.venv/` at the project root and installs there. To make
uv respect the active venv, pass `--active` to the uv command, or
set `UV_PROJECT_ENVIRONMENT` to its absolute path. ([uv#14747](https://github.com/astral-sh/uv/issues/14747))

---

## UVP-023 — Configure `default-groups` deliberately

**What.** `[tool.uv] default-groups` controls which `[dependency-groups]`
get installed when you run `uv sync` (or `uv run`) without explicit
`--group` / `--no-group` flags. The default is `["dev"]` — meaning
bare `uv sync` installs the `dev` group.

**Why.** Two failure modes from leaving it unconsidered:

1. **Production accidentally installs dev deps.** A deploy script that runs `uv sync --locked` (without `--no-dev` or `--no-default-groups`) installs the `dev` group. This is a quiet bug — the deploy "works," but the image is bloated by pytest + ruff + mypy and any of their transitives. The fix is *either* `--no-dev` at the call site (UVP-020) *or* a deliberate `default-groups` config.
2. **New contributors don't get expected groups.** If you have a `test` group that you expect everyone to install, but `default-groups = ["dev"]` doesn't include it, a fresh `uv sync` leaves `test` uninstalled. Newcomers fail to run tests and don't know why.

The right shape depends on your project:

```toml
# Default — dev group only
[tool.uv]
default-groups = ["dev"]

# Multi-group expectation — every contributor needs both
[tool.uv]
default-groups = ["dev", "test"]

# All groups by default — heavy but simplest mental model
[tool.uv]
default-groups = "all"

# Nothing by default — production-first, opt-in dev
[tool.uv]
default-groups = []
```

**How.** Decide based on your team's expected developer workflow:

- **Hobby project / small team**: `default-groups = ["dev"]` (default) is fine. Bare `uv sync` gives you what you need.
- **Multi-group, team workflow**: `default-groups = ["dev", "test"]` or similar. Document in CONTRIBUTING.md that bare `uv sync` is the right starting point.
- **Deploy-first**: `default-groups = []`. Bare `uv sync` installs only project deps. Developers opt in: `uv sync --group dev`. Forces explicit deploy steps.

To override the configured default groups for a single command without
editing `pyproject.toml` — e.g. a production-image build in CI — set
`UV_NO_DEFAULT_GROUPS=1` in the environment (equivalent to
`--no-default-groups`).

The flag mapping:

- `--no-dev` = `--no-group dev`. Targets one group.
- `--no-default-groups` = excludes everything in `default-groups`.
- `--all-groups` = includes every group regardless of config.
- `--group <name>` = adds a group not in `default-groups`.

**When NOT to apply.** Solo single-person projects with one group
(`dev`) — the default works fine; don't over-configure. The rule
applies once you have multiple groups or multiple contributors with
different expected setups.

---

## UVP-024 — PEP 723 inline scripts: manage deps with `uv add --script`, lock with `uv lock --script`

**What.** Single-file Python scripts can declare their own
dependencies inline via [PEP 723](https://peps.python.org/pep-0723/)
script metadata blocks. uv has first-class support: add, lock, and
run the script as a self-contained unit, independent of any
surrounding project's `pyproject.toml` or `uv.lock`.

```bash
uv init --script analyze.py --python 3.12      # scaffold the metadata block
uv add --script analyze.py httpx pandas        # write deps into the block
uv lock --script analyze.py                    # produce analyze.py.lock
uv run --script analyze.py                     # run in an isolated env
```

See the [uv scripts guide](https://docs.astral.sh/uv/guides/scripts/).

**Why.** Hand-editing the inline metadata block works but is
fragile (the field is a TOML document embedded in `# ///` comments;
typos in the format produce confusing errors). And — critically —
PEP 723 scripts run in an **isolated environment that ignores the
surrounding project's lockfile**:

1. **Project deps are invisible inside the script env.** If `analyze.py` lives at the root of a uv project with `httpx` in `[project.dependencies]`, `uv run --script analyze.py` still won't have httpx available unless `analyze.py`'s inline block declares it. This is by design (scripts are portable; they should work checked out alone) but trips up users who expect "run script in this project" semantics. For project-aware execution use `uv run analyze.py` *without* `--script`.
2. **No lockfile by default.** `uv run --script` happily re-resolves on every cold cache, mirroring the `uvx <tool>` footgun (UVP-041). Pin the script's deps with `uv lock --script analyze.py`, which produces a sibling `analyze.py.lock` file. Commit the lockfile if the script is shared.
3. **Editing the metadata by hand drifts from intent.** `uv add --script` writes the spec uv expects to read back; hand-edits ("oh, I'll just tighten the version") often work but occasionally break the field encoding.

**How.**

```python
# analyze.py — managed by `uv add --script`
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "httpx>=0.27",
#   "pandas>=2.2",
# ]
# ///
import httpx
import pandas as pd
# ... script body
```

```bash
# bump a dep
uv add --script analyze.py 'httpx>=0.28'

# refresh the lockfile
uv lock --script analyze.py
git add analyze.py analyze.py.lock

# run with the locked deps
uv run --script analyze.py

# upgrade-and-relock in one shot
uv lock --script analyze.py --upgrade-package httpx
```

For a script that genuinely needs to import the surrounding project,
**don't use `--script`** — make the script a project entry point
(`src/myapp/scripts/analyze.py` + a `[project.scripts]` entry) and
invoke via `uv run analyze`.

**When NOT to apply.** Scripts that need to import the parent
project — they belong in the project's package, not in a PEP 723
file. Also: throwaway one-liners where the cold-cache resolve cost
is negligible; the inline block is overhead for a five-line shell
replacement.

---

## UVP-025 — Use `[[tool.uv.index]]` named indexes; mark private indexes `explicit = true`

**What.** Configure additional package indexes — internal company
registries, PyTorch's CUDA wheel host, the TestPyPI staging
registry — via `[[tool.uv.index]]` blocks in `pyproject.toml`, **not**
via deprecated `--index-url` / `--extra-index-url` flags or
`[tool.uv] index-url` / `extra-index-url`. For private indexes, set
`explicit = true` so packages only resolve there when pinned via
`[tool.uv.sources]`.

```toml
[[tool.uv.index]]
name = "internal"
url = "https://pypi.corp.example/simple"
explicit = true                  # packages must opt in via [tool.uv.sources]

[[tool.uv.index]]
name = "pypi"
url = "https://pypi.org/simple"
default = true

[tool.uv.sources]
internal-lib = { index = "internal" }
```

See the [uv indexes docs](https://docs.astral.sh/uv/concepts/indexes/).

**Why.** Three real failure modes from the older / unsafe shapes:

1. **Dependency confusion via `--extra-index-url`.** When two indexes both serve a package named `internal-lib` — one your real internal one, one a public-PyPI squat — uv's default `index-strategy = "first-index"` picks the first match. With `--extra-index-url` (no `explicit`), the resolver checks *all* indexes for *every* package, so a typo or a typosquatter can serve your "private" package from public PyPI. This is the [pytosquatting attack class](https://pytosquatting.overtag.dk/) that hit PyTorch's nightly index in 2023. `explicit = true` forces a `[tool.uv.sources]` pin: the index is only consulted for packages you've explicitly routed there.
2. **`index-strategy = "unsafe-best-match"` defeats `first-index` safety.** The strategy controls how uv picks between versions across indexes. The default (`first-index`) stops at the first index that has the package; `unsafe-best-match` searches *all* indexes and picks the highest version. The latter brings back the dependency-confusion vector — a higher version on public PyPI overrides a pinned lower version on your internal. The name is honest: it's unsafe. Never set this for private-index setups.
3. **Deprecated `--index-url` / `[tool.uv] index-url` is ambiguous about precedence.** Newer `[[tool.uv.index]]` blocks have clear ordering (top-to-bottom, with `default = true` marking the fallback). The old single-field form silently overrides PyPI as the default; mixed configs (some old, some new) produce surprising resolution.

**How.**

```toml
# pyproject.toml — multiple indexes, safe by default

[[tool.uv.index]]
name = "pypi"
url = "https://pypi.org/simple"
default = true                   # fallback for everything not pinned

[[tool.uv.index]]
name = "internal"
url = "https://pypi.corp.example/simple"
explicit = true                  # never auto-consulted; opt-in only

[[tool.uv.index]]
name = "pytorch-cu121"
url = "https://download.pytorch.org/whl/cu121"
explicit = true

[tool.uv.sources]
internal-models = { index = "internal" }
torch = { index = "pytorch-cu121" }

# Strategy: keep the safe default. Do NOT set:
# [tool.uv]
# index-strategy = "unsafe-best-match"   # disables dep-confusion protection
```

Authentication for private indexes goes through environment variables
that match the index name:

```bash
export UV_INDEX_INTERNAL_USERNAME="${INTERNAL_USER}"
export UV_INDEX_INTERNAL_PASSWORD="${INTERNAL_TOKEN}"
```

In CI, set those via the runner's secret store; never commit credentials.

**When NOT to apply.** Single-index projects that only use public
PyPI — no `[[tool.uv.index]]` block needed; PyPI is the default.
This rule kicks in once you have a *second* index.

---


## UVP-066 — `uv run --with` builds an ephemeral overlay; add `--isolated` for true isolation

**What.** Since uv 0.8.0, `uv run --with <pkg>` layers an *ephemeral*
environment on top of the project venv rather than mutating it. The
overlay still sees the project's packages; to run a tool with zero
project bleed-through, use `uv run --isolated --with <pkg>` (or
`uvx --isolated <pkg>`).

**Why.** Before 0.8.0, `uv run --with black` installed into the shared
project cache, so two concurrent CI jobs requesting different `black`
versions could race and one would pick up the wrong one. The ephemeral
layering removes that hazard. The flip side: users who expect `--with` to
produce a *clean* environment are surprised when `import project_pkg`
still works — that's what `--isolated` is for.

**How.**

```bash
uv run --with black black .              # overlay; project still importable
uv run --isolated --with black black .   # project packages NOT visible
uvx --isolated cowsay hi                 # same, via uvx
```

**When NOT to apply.** When the tool legitimately needs to import the
project (a formatter that reads your project's config) — add it to
`[dependency-groups]` (UVP-040) instead of `--with`.

---

## UVP-068 — Use `--active` (or `UV_ACTIVE=1`) to make uv respect an activated venv

**What.** By default uv ignores `VIRTUAL_ENV` and manages its own `.venv`
at the project root. The `--active` flag (and `UV_ACTIVE=1`, since uv
0.5.29) tells uv to use the currently-activated environment instead.

**Why.** This is the most common "uv is ignoring my venv" confusion:
`source custom-venv/bin/activate && uv sync` silently creates a *second*
`.venv` at the project root rather than syncing into the activated one.
The right tool depends on intent — a fixed path wants
`UV_PROJECT_ENVIRONMENT` (UVP-022); deferring to whatever's active wants
`--active`.

**How.**

```bash
source /path/to/custom-venv/bin/activate
uv sync --active        # sync into the activated venv, not ./.venv
```

**When NOT to apply.** Projects with a fixed environment path — set
`UV_PROJECT_ENVIRONMENT` (UVP-022) instead. Don't export `UV_ACTIVE=1`
globally in CI, where the "active" venv may be an unrelated leftover from
a previous step; pin the path explicitly there.

---

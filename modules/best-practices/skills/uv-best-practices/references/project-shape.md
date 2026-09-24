# UVP project-shape rules

Detailed entries for `UVP-001..UVP-008` and `UVP-016`. Each follows
the four-part **What / Why / How / When NOT to apply** shape.

Citations point at the [uv concepts docs](https://docs.astral.sh/uv/concepts/projects/)
and [PEP 735](https://peps.python.org/pep-0735/). Verify version-specific
syntax against the current docs before claiming defaults — uv ships
fast and field names have changed (notably `[tool.uv.dev-dependencies]`
→ `[dependency-groups]`).

---

## UVP-001 — Use `[dependency-groups]` (PEP 735), not deprecated `[tool.uv.dev-dependencies]`

**What.** Declare development-only dependencies in
[PEP 735](https://peps.python.org/pep-0735/) `[dependency-groups]`,
not the uv-specific `[tool.uv.dev-dependencies]`. The latter is
documented as "not recommended anymore" in
[uv's settings reference](https://docs.astral.sh/uv/reference/settings/#dev-dependencies);
the former is a real Python standard supported by pip, hatch, and the
rest of the ecosystem.

**Why.** Three failure modes:

1. **Tool portability.** `[tool.uv.dev-dependencies]` is uv-only. Other tools (pip ≥25.1, hatch, PDM) read `[dependency-groups]`. A project pinned to the old field can't be installed by anything else without rewriting.
2. **Hidden duplication.** If you have *both* `[tool.uv.dev-dependencies]` and `[dependency-groups]`, uv merges them into the `dev` group (and warns that the old field is deprecated). The same package can then appear twice with different version constraints. uv applies both, so the resolved range is their intersection, and constraints that don't overlap make the lock fail as unsatisfiable, with no hint that the second constraint came from the other table.
3. **Future removal.** Astral has telegraphed eventual removal of `[tool.uv.dev-dependencies]`. New projects pinned to it accumulate migration debt for zero benefit.

**How.**

```toml
# pyproject.toml
[project]
name = "myapp"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["fastapi", "pydantic>=2"]

[dependency-groups]
dev = [
  "pytest>=8",
  "pytest-cov",
  "ruff>=0.6",
  "mypy",
]
docs = [
  "mkdocs",
  "mkdocs-material",
]
```

Install the default groups: `uv sync` (`default-groups` is `["dev"]`, so only `dev` installs — not `docs`).
Install all groups: `uv sync --all-groups`.
Install only the project: `uv sync --no-default-groups`.
Install a specific group: `uv sync --group docs`.

**When NOT to apply.** Two narrow cases:

1. **Backward compat with very old uv versions** (before 0.4.27, the first release that reads `[dependency-groups]`). If your team is genuinely pinned to an old uv, keep `[tool.uv.dev-dependencies]`. Otherwise migrate.
2. **You're publishing a library and want consumers to install dev deps as PyPI extras.** Extras (`[project.optional-dependencies]`) are different from dependency groups — extras ship in the wheel metadata; groups do not. If consumers need to `pip install yourpkg[test]`, use extras. Groups are for *your* dev workflow; extras are for *your consumers*.

---

## UVP-002 — Compose groups with `include-group`; never duplicate packages across groups

**What.** When two groups share dependencies, use PEP 735's
`include-group` directive rather than copy-pasting packages into both
group lists.

**Why.** Duplication is a maintenance trap. Bumping `pytest` from
`>=8` to `>=8.1` in `test` but forgetting to bump the copy in `ci`
creates a resolver that has to pick a version satisfying *both*
constraints — works until it doesn't, and the failure mode is a
cryptic resolution error five months later when an unrelated package
tightens its peer constraint.

`include-group` makes the relationship explicit: `ci` *includes*
`test`, which means dependencies and version constraints flow through
exactly once.

**How.**

```toml
[dependency-groups]
test = ["pytest>=8.1", "pytest-cov", "coverage"]
ci = [
  {include-group = "test"},        # pulls in test deps verbatim
  "tox",                            # CI-only addition
]
docs = ["mkdocs", "mkdocs-material"]
all = [
  {include-group = "test"},
  {include-group = "docs"},
]
```

PEP 735 prohibits cycles — `a` including `b` including `a` raises a
resolution error at install time. Linear or DAG-shaped inclusion is
fine and common.

**When NOT to apply.** Never. Composing a parent from groups that
share nothing is fine too: uv's own example builds `dev` from disjoint
`lint` and `test` groups
([uv docs — nesting groups](https://docs.astral.sh/uv/concepts/projects/dependencies/#nesting-groups)).

---

## UVP-003 — `requires-python` is a floor (`">=3.X"`), never an upper-bounded range

**What.** Set `requires-python` to a lower bound only:
`requires-python = ">=3.12"`. Don't write `">=3.12,<3.13"` or
`">=3.12,<4.0"`.

**Why.** An upper bound on `requires-python` is *strongly* user-hostile:

- **Users on a newer Python get a hard install failure.** `pip install myapp` on Python 3.13 errors with "package requires Python <3.13" — even though your code would have worked fine. There's no override.
- **Transitive blast radius.** When *your* project is a dependency of someone else's, your upper bound caps theirs too. A single capped dep can lock an entire transitive tree to an obsolete Python.
- **It rarely buys what people think it does.** People add `<4.0` "for safety" — but the resolver already only picks dep versions compatible with whatever Python is actually running. Capping `requires-python` doesn't add safety; it just blocks future Pythons.

The argument *for* an upper bound is sometimes "I haven't tested 3.14
yet." That belongs in a CHANGELOG note or a CI matrix, not in
`requires-python`. See the [Henry Schreiner write-up](https://iscinumpy.dev/post/bound-version-constraints/)
on why upper bounds on Python versions are an antipattern.

**How.**

```toml
[project]
name = "myapp"
requires-python = ">=3.12"          # good
# requires-python = ">=3.12,<3.14"  # bad — caps users
# requires-python = "~=3.12"        # bad — same problem (`~=3.12` means `>=3.12, ==3.*`: caps the major)
```

If you discover your package genuinely doesn't work on a new Python,
release a patch version that *capse the broken dependency*, not
`requires-python`.

**When NOT to apply.** A platform with a hard runtime version (AWS
Lambda runtime, App Engine standard) pins the Python version
externally. Even then, pin via deploy config / `.python-version`
(UVP-050), not `requires-python`.

---

## UVP-004 — Git and path deps go in `[tool.uv.sources]`, not raw URLs in `[project.dependencies]`

**What.** When a dependency comes from a git repo or a local path,
declare a normal PEP 508 spec in `[project.dependencies]` and the
source override in `[tool.uv.sources]`. Don't put `git+https://...`
or `file://...` URLs directly in `[project.dependencies]`.

**Why.** Two real failures:

1. **`uv export --format requirements.txt` breaks.** When you (or a downstream consumer) need a requirements.txt for compatibility (UVP-061), `uv export` can't represent a raw git URL inside `[project.dependencies]` portably across tools — different installers interpret `git+https://...` slightly differently. Sources resolve to standard `name==version` lines in export.
2. **`pip install` of the published package picks up the git URL as a dependency.** Anyone who installs your published wheel from PyPI inherits a hard dep on git + network access at install time. `[tool.uv.sources]` is uv-specific metadata and *doesn't ship in the wheel*; the published package depends only on the normalized spec.

**How.**

```toml
[project]
name = "myapp"
dependencies = [
  "httpx",                    # normal PyPI dep
  "internal-lib",             # name only — source is below
]

[tool.uv.sources]
# git dep — pinned to a tag for reproducibility
internal-lib = { git = "ssh://git@github.com/myorg/internal-lib", tag = "v1.2.3" }

# alternative: pin to a rev (commit SHA) for tighter reproducibility
# internal-lib = { git = "...", rev = "abc123..." }

# local path dep, editable for dev workflow
local-helper = { path = "../local-helper", editable = true }
```

For workspace members, the source is `{ workspace = true }`:

```toml
[tool.uv.sources]
sibling-pkg = { workspace = true }
```

**When NOT to apply.** Throwaway prototypes that won't be published
and won't be exported — a raw `git+https://...` is shorter. Don't do
this in anything that ships.

---

## UVP-005 — `uv init --lib` for libraries (src/ + build-system); bare `uv init` for apps (flat, `package = false`)

**What.** Pick the layout intentionally:

| Command | Layout | Build system | Project install |
|---|---|---|---|
| `uv init` | flat | none | `package = false` (project is *not* installed into the venv) |
| `uv init --app` | flat | none | `package = false` (same as bare `uv init`) |
| `uv init --lib` | `src/` | `uv_build` | editable install of the project |
| `uv init --package` | `src/` | `uv_build` | editable install (same as `--lib` for layout) |

The mode you want depends on whether your project is *consumed*
(library: yes, app: no) and whether you need to `import myapp`
inside the project itself (almost always yes for libraries, often
yes for apps too).

**Why.** Three failure modes from picking wrong:

1. **`import myapp` fails in tests.** If you ran bare `uv init` (which sets `package = false`), uv doesn't install the project. Tests that do `from myapp import x` fail with `ModuleNotFoundError`. The fix is either `--package` mode or adding `[build-system]` and `tool.uv.package = true` by hand.
2. **`uv build` produces nothing.** Without `[build-system]`, you can't build a wheel. If you ever want to publish, you have to retrofit the build-system table, which means choosing a backend without thinking about it.
3. **Accidental imports from project root.** A flat layout means `myapp/` is at the repo root next to `tests/`. When you run pytest from the repo root, Python finds the *source tree* `myapp/` ahead of any installed version — meaning `__init__.py`'s side effects and import order behave differently in dev vs. in production. The `src/` layout (`src/myapp/`) forces tests to import the *installed* version, matching production.

**How.**

```bash
# library — most common for things you'll publish
uv init --lib mylib
# creates:
#   mylib/
#     pyproject.toml      # has [build-system] = uv_build (UVP-029)
#     src/mylib/__init__.py
#     src/mylib/py.typed
#     README.md
#     .python-version

# app — services, CLIs you won't publish
uv init myapp
# creates:
#   myapp/
#     pyproject.toml      # no [build-system]; package = false
#     main.py             # at repo root
#     README.md
#     .python-version
```

For an app that *also* wants `import myapp` to work in tests, use
`--package` (which is the same shape as `--lib` but signals "app
that's installable"):

```bash
uv init --package myapp
```

**When NOT to apply.** Single-file scripts that never grow into a
package — those don't need `uv init` at all; use `uv run --script
file.py` with inline metadata (PEP 723).

---

## UVP-006 — Use a workspace only when members share lockfile resolution

**What.** [uv workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/)
let multiple packages in one repo share a single `uv.lock`. Members
list under `[tool.uv.workspace]` in the root pyproject.toml. This is
the right shape **only when** the members' dependency requirements
genuinely resolve to a single coherent set.

**Why.** Workspaces force a single shared resolution. If member A
needs `pydantic==1.x` and member B needs `pydantic==2.x`, uv
*cannot* satisfy both — workspaces don't support per-member virtual
environments. The resolution error is loud but the fix is
"un-workspace your repo," which is a major refactor.

Two other ways workspaces silently hurt:

1. **`requires-python` becomes the intersection.** uv resolves the whole workspace against the *strictest* member's floor. Adding a new member with `requires-python = ">=3.13"` silently raises the floor on every existing member that was happy with 3.10 — including their tests and CI.
2. **`default-groups` is workspace-wide.** Each member can't have its own. If one member has heavy dev deps and another is lean, both pay the cost.

**How — when a workspace is right.**

```toml
# root pyproject.toml — at the repo root
[project]
name = "monorepo-root"
version = "0"
requires-python = ">=3.12"

[tool.uv.workspace]
members = ["packages/*"]
exclude = ["packages/seeds"]
```

Each member is a normal package with its own `pyproject.toml`.

The historical "leading `./` in member paths breaks discovery"
footgun ([uv#16285](https://github.com/astral-sh/uv/issues/16285))
was fixed in a late-2025 uv release. Projects on older uv versions
should still write `"packages/*"`, not `"./packages/*"`; on 0.9.3+
either form works, but the bare-glob form remains the convention.

**When NOT to apply.**

- **Conflicting deps.** Two services that need different major versions of the same library — separate them into independent projects with independent lockfiles.
- **Different Python floors.** A legacy service on 3.10 and a new service on 3.13 — keep separate.
- **You just want code colocation, not shared resolution.** A repo with multiple unrelated projects works fine with separate pyproject.toml files and no workspace; the developer experience is barely worse and resolution stays decoupled.

Workspaces are the right tool for **one logical product spread across
linked packages**, not for **a monorepo with N services**.

---

## UVP-007 — Workspace inter-member deps need both `[project.dependencies]` and `[tool.uv.sources]` with `workspace = true`

**What.** When workspace member `app` depends on workspace member
`lib`, you need *two* entries in `app`'s pyproject.toml:

```toml
# packages/app/pyproject.toml
[project]
dependencies = ["lib"]              # the regular PEP 508 dep

[tool.uv.sources]
lib = { workspace = true }          # tells uv "resolve this from the workspace, not PyPI"
```

**Why.** Without the `[tool.uv.sources]` entry, uv tries to resolve
`lib` from PyPI. If `lib` doesn't exist on PyPI (almost always the
case for internal workspace packages), the resolver fails with a
"could not find a version that satisfies the requirement" error —
not "did you mean the workspace member?" The error points at PyPI;
the fix is in your local config. This is the most common workspace
setup footgun (per
[dev.to/aws "3 things I wish I knew"](https://dev.to/aws/3-things-i-wish-i-knew-before-setting-up-a-uv-workspace-30j6)).

**How.** Every inter-member dep needs both entries. There's no shorthand.

```toml
# packages/api/pyproject.toml
[project]
name = "api"
dependencies = [
  "fastapi",
  "models",                          # workspace member
  "shared-types",                    # workspace member
]

[tool.uv.sources]
models = { workspace = true }
shared-types = { workspace = true }
```

Optionally, you can mark a workspace member as not packaged
(`package = false` in its own pyproject) if it's purely an internal
library that should never be built into a wheel.

**When NOT to apply.** If you're not using workspaces (UVP-006), this
rule is moot. Within a workspace, *always* both entries.

---

## UVP-008 — Pin a minimum uv version with `[tool.uv] required-version`

**What.** Declare the lowest acceptable uv binary version in
`pyproject.toml` so contributors, CI runners, and production builds
all use a uv new enough to handle the project's config correctly:

```toml
[tool.uv]
required-version = ">=0.5.14"
```

The field was added in uv 0.5.14
([changelog](https://github.com/astral-sh/uv/blob/main/CHANGELOG.md)).
On older uv binaries the field is ignored; on newer ones, uv refuses
to operate if the running binary is below the floor.

**Why.** Without `required-version`, version skew between developers,
CI runners, and production images causes silent resolver-behavior
differences:

1. **Resolver bug fixes change which versions get picked.** uv ships fast — multiple resolver fixes per minor release. A developer on uv 0.7 and a CI runner on uv 0.5 can produce different `uv.lock` outputs from the same `pyproject.toml`. The diff looks like "someone ran `uv lock` and bumped things they didn't intend to" but it's actually two different resolvers disagreeing.
2. **Newer config fields are silently ignored on old binaries.** A project that adopts `[tool.uv] conflicts` (UVP-016, requires 0.5.3) or PEP 751 export (requires 0.6.15) "works" on an older uv because the binary skips fields it doesn't understand. The failure is downstream — a conflict isn't enforced, a feature flag has no effect — and very hard to trace back to the version skew.
3. **CI cache from one uv version installed by another.** Mixing uv versions across cache writers and readers occasionally surfaces hash mismatches or "stale cache entry" errors that vanish after `uv cache prune`.

`required-version` makes the floor explicit and machine-checkable.
Bump it as you adopt features that require newer uv.

**How.**

```toml
# pyproject.toml — pin the minimum that supports the features you use
[tool.uv]
required-version = ">=0.5.14"      # baseline (this field itself)

# Bump as you adopt newer features:
# required-version = ">=0.6.0"      # OIDC trusted publishing graduated (UVP-027)
# required-version = ">=0.6.10"     # `uv sync --check` (UVP-015)
# required-version = ">=0.6.15"     # `uv export --format pylock.toml` (UVP-062)
# required-version = ">=0.7.0"      # `uv version` manages project version (UVP-053)
# required-version = ">=0.8.0"      # uv_build is the default init backend (UVP-029); --check exits 1 not 2; `uv version` errors outside a project
# required-version = ">=0.9.0"      # Python 3.14 becomes uv's default managed Python (UVP-073)
# required-version = ">=0.10.0"     # add-bounds + `uv workspace list` stable (UVP-063, UVP-069)
# required-version = ">=0.11.4"     # `uv lock --upgrade-group` (UVP-070)
```

Combine with the GitHub Actions `setup-uv` `version:` input (or the
container image tag) to make the floor enforced end-to-end:

```yaml
- uses: astral-sh/setup-uv@<sha> # v8.1.0
  with:
    version: "0.7.19"             # ≥ required-version
    enable-cache: true
```

**When NOT to apply.** Throwaway scripts and prototypes where no team
is involved and the only uv binary is your laptop's. Once a project
has *any* second user (a colleague, CI, a Docker build), set
`required-version`.

---

## UVP-016 — Declare mutually-exclusive extras/groups with `[tool.uv] conflicts`

**What.** When two extras (or two dependency groups) install
incompatible packages — the canonical case is CPU vs GPU builds of
PyTorch — declare them as conflicting so uv resolves each branch
separately instead of attempting a single universal resolution:

```toml
[project.optional-dependencies]
cpu = ["torch>=2.4 ; platform_machine != 'aarch64'"]
gpu = ["torch>=2.4"]

[tool.uv]
conflicts = [
  [
    { extra = "cpu" },
    { extra = "gpu" },
  ],
]
```

The field was added in uv 0.5.3 and is documented under
[uv resolution concepts](https://docs.astral.sh/uv/concepts/resolution/#conflicting-dependencies).

**Why.** Without `conflicts`, uv tries to lock a single environment
that satisfies *both* extras simultaneously. For mutually-incompatible
extras this fails in one of two ugly ways:

1. **Resolution error.** uv reports "no version of `torch` satisfies both `+cpu` and `+cu121` index requirements" — the error mentions the package but not that the *config* is asking for an impossible thing. Users add `--resolution=lowest` or pin versions, neither of which helps.
2. **Wrong wheel installed.** If both extras happen to share a version that "satisfies" both constraints on paper (e.g. the CPU wheel matches the GPU version string), uv picks one and the lockfile pins it. Then `uv sync --extra gpu` silently installs the CPU wheel because that's what was locked. The runtime error ("no CUDA device available") shows up at first GPU op.

Declaring the conflict tells uv "fork the resolution: lock one branch
per extra, never mix them." The lockfile encodes both forks and
`--extra cpu` / `--extra gpu` each get the right wheel.

**How.**

```toml
# PyTorch CPU / CUDA / ROCm — three-way conflict
[project.optional-dependencies]
cpu  = ["torch>=2.4"]
cu121 = ["torch>=2.4"]
rocm = ["torch>=2.4"]

[tool.uv]
conflicts = [
  [
    { extra = "cpu" },
    { extra = "cu121" },
    { extra = "rocm" },
  ],
]

[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true

[[tool.uv.index]]
name = "pytorch-cu121"
url = "https://download.pytorch.org/whl/cu121"
explicit = true

[tool.uv.sources]
torch = [
  { index = "pytorch-cpu",  extra = "cpu" },
  { index = "pytorch-cu121", extra = "cu121" },
]
```

`conflicts` also works for dependency groups (PEP 735), using the
`group` key instead of `extra`:

```toml
[dependency-groups]
backend-redis = ["redis>=5"]
backend-memcached = ["pymemcache>=4"]

[tool.uv]
conflicts = [
  [
    { group = "backend-redis" },
    { group = "backend-memcached" },
  ],
]
```

Each entry in `conflicts` is an array of 2+ extras/groups; the outer
array can hold multiple independent conflict sets.

**When NOT to apply.** Extras / groups that *can* coexist — the
common case. Adding entries to `conflicts` for compatible extras
makes uv fork resolution unnecessarily, bloating the lockfile and
slowing every `uv sync`. Only declare a conflict when the packages
involved are genuinely mutually exclusive.

---

## UVP-063 — Set `[tool.uv] add-bounds` to control how `uv add` writes constraints

**What.** The `add-bounds` setting (stable since uv 0.10.0) controls the
default version constraint `uv add <pkg>` writes: `"lower"` (default —
`>=1.2.3`), `"major"` (`>=1.2.3,<2`), `"minor"` (`>=1.2.3,<1.3`), or
`"exact"` (`==1.2.3`). Override per-invocation with `uv add --bounds <value>`.

**Why.** The default `"lower"` keeps future patch/major upgrades open,
which is correct for most application deps and avoids the upper-bound
trap (UVP-003). A team that wants tighter SemVer gating can set this once
in `[tool.uv]` instead of hand-editing the constraint after every
`uv add`, so the policy is declared rather than remembered.

**How.**

```toml
[tool.uv]
add-bounds = "lower"   # default — writes >=X.Y.Z
# add-bounds = "exact" # writes ==X.Y.Z, for pinned infra only
```

**When NOT to apply.** `"exact"` defeats the point of `uv.lock` for
ordinary projects (every `uv add` adds a pin you must bump by hand) —
reserve it for tooling/infra. Never set `"minor"`/`"major"` on a
*published library*: tight upper bounds on your deps propagate pain to
your consumers (UVP-003 applies to your own deps too).

---

## UVP-064 — Bound lockfile platform scope with `environments` / `required-environments`

**What.** Two `[tool.uv]` settings shape which platform/Python
combinations appear in `uv.lock`: `environments` *restricts* the lock to
the listed PEP 508 markers (shrink it), while `required-environments`
*guarantees* wheels are resolved for the listed platforms even if the
current machine doesn't need them (catch gaps early).

**Why.** Without `environments`, uv builds a universal lock spanning
every platform in `requires-python`'s range — bloat for a service that
only ships on Linux x86-64. Without `required-environments`, a Linux CI
job won't notice that a dependency has no macOS-arm64 wheel until someone
deploys there and the install fails, instead of CI catching it.

**How.**

```toml
# restrict (service that only runs on Linux)
[tool.uv]
environments = ["sys_platform == 'linux'"]

# or guarantee specific targets always resolve
[tool.uv]
required-environments = [
  "sys_platform == 'darwin' and platform_machine == 'arm64'",
  "sys_platform == 'linux' and platform_machine == 'x86_64'",
]
```

**When NOT to apply.** Don't set `environments` on a *published library*
— contributors on any platform need a universal lock. Use it for
apps/services with a known deploy target; reach for `required-environments`
when CI and production run on different platforms.

---

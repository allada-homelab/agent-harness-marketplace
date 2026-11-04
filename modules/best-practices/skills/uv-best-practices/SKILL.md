---
name: uv-best-practices
description: Use when working with uv, Astral's Python package and project manager — `uv sync` / `add` / `lock` / `run` / `tool` / `build` / `publish`, `uvx`, a `uv.lock`, or a `pyproject.toml` with `[tool.uv]` or `[dependency-groups]`, including workspaces, private registries, CI, publishing and migrating from pip, poetry, PDM or Hatch. Covers the UVP- rule family. For uv inside a Dockerfile, use containers-best-practices.
user-invocable: false
---

# uv best practices

A curated rule set for using [uv](https://github.com/astral-sh/uv) as
the Python project tool — outside of containers. Container-side uv
rules (`UV-*`) cover Dockerfile-specific patterns and live in
[`containers-best-practices/references/uv-python.md`](../containers-best-practices/references/uv-python.md);
this skill covers everything else.

Each rule has a stable ID and a one-line summary. Full **What / Why /
How / When-not-to-apply** entries live in `references/`.

## When to apply this skill

Activate when any of these are true:

- The user mentions `uv`, `uvx`, `uv sync`, `uv add`, `uv lock`, `uv tool`, `uv run`, `uv export`, or `uv venv`.
- A `pyproject.toml` in context has `[tool.uv]`, `[dependency-groups]`, or `[tool.uv.workspace]`.
- A `uv.lock` or `.python-version` file is present in the repo.
- The user asks about Python project layout, lockfiles, workspaces, dependency groups, or Python version pinning, and uv is the package manager.
- Migrating a project from pip / poetry / pdm / pip-tools / hatch to uv.

For Dockerfile-specific uv patterns (multi-stage builds, cache
mounts, `UV_COMPILE_BYTECODE`, system-Python installs), see the
`containers-best-practices` skill's `UV-*` rules instead.

## Coverage

Topics the rule index below covers, for matching against the task at hand:

- **Project shape** — `[dependency-groups]` (PEP 735) vs deprecated `[tool.uv.dev-dependencies]`, group composition via `include-group`, `[tool.uv] required-version`, conflicting extras/groups (`[tool.uv] conflicts`).
- **Lockfile** — `uv.lock` hygiene and commit policy, `--locked` vs `--frozen` vs `--check` semantics, `pylock.toml` (PEP 751) export.
- **Dependency sources** — `[tool.uv.sources]` and `[[tool.uv.index]]` for git / path / private-registry dependencies.
- **Workspaces** — `[tool.uv.workspace]` members, shared vs per-member locking.
- **Tools & scripts** — `uv tool install` vs `uv add --dev` vs `uvx`, PEP 723 inline scripts (`uv run --script`, `uv lock --script`).
- **Python versions** — `.python-version` vs `requires-python`, `uv version` (project) vs `uv self version` (binary), `UV_PYTHON_DOWNLOADS`.
- **CI & environment** — `uv sync` in CI, `astral-sh/setup-uv` caching, `UV_LINK_MODE` / `UV_PROJECT_ENVIRONMENT`, the production incantation `uv sync --locked --no-dev --no-editable`.
- **Publishing** — `uv build --no-sources`, `uv publish` with OIDC trusted publishing, the native `uv_build` PEP 517 backend.
- **Security** — `uv audit` for OSV vulnerability scans.
- **Migration** — moving from pip / poetry / PDM / pip-tools / Hatch via `migrate-to-uv`.

Rules were last checked against uv 0.13.7 (commit 316c827) by the
`rules-sweep` command in the `best-practices-maintainer` module; a
new sweep starts from that release.

## How to use the rule index

1. Scan the relevant section(s) below for rule IDs that apply.
2. For each rule, open the corresponding `references/` file and read **only that rule's entry** — they're keyed by ID.
3. Cite the rule ID when explaining a change to the user (e.g. "Switching to dependency groups — UVP-001").

## Applicability

Rules with no `when:` tag apply to every uv project. A tagged rule
applies only when its tag's check matches the repository. To audit a
repo, run each check once, then read the untagged rules plus the rules
whose tag matched.

| Tag | Applies when | Detect |
|---|---|---|
| `ci` | CI runs uv | `grep -lE 'astral-sh/setup-uv\|ghcr.io/astral-sh/uv\|(^\|[ ;])uvx? ' .github/workflows/*.y*ml .gitlab-ci.yml` |
| `workspace` | The repo is a uv workspace | `grep -q '^\[tool\.uv\.workspace\]' pyproject.toml` |
| `packaged` | The project declares a build backend | `grep -qE '^\[build-system\]\|^package *= *true' pyproject.toml` |
| `publish` | The repo uploads distributions | `grep -rlE 'uv publish\|gh-action-pypi-publish\|twine upload\|publish-url' .github/workflows .gitlab-ci.yml scripts/ Makefile justfile pyproject.toml` |
| `private-index` | A non-default index is configured | `[[tool.uv.index]]`, `index-url` / `extra-index-url` / `keyring-provider` in `[tool.uv]` or `uv.toml`, or `UV_INDEX*` / `UV_KEYRING_PROVIDER` / `uv auth login` in CI, scripts or env files |
| `scripts` | The repo has PEP 723 scripts | `grep -rlE '^# /// script' --include='*.py' .` |
| `tools` | uvx or `uv tool` is invoked | `grep -rlE '(^\|[ ;"])(uvx \|uv tool )' .github/ .gitlab-ci.yml .pre-commit-config.yaml Makefile justfile scripts/ docs/ README*` |
| `uv-settings` | Advanced resolver settings are set | `[tool.uv]` or `uv.toml` sets `exclude-newer`, `environments`, `required-environments`, `prerelease`, `override-dependencies`, `constraint-dependencies`, `conflicts`, `add-bounds`, `no-build-isolation` or `no-build-isolation-package` |
| `env-overrides` | Environment, cache or TLS behavior is overridden | CI, a Dockerfile, `.envrc` or `uv.toml` sets `UV_LINK_MODE` / `link-mode`, `UV_PROJECT_ENVIRONMENT`, `UV_CACHE_DIR`, `SSL_CERT_FILE`, `SSL_CERT_DIR`, `system-certs` / `UV_SYSTEM_CERTS`, or `allow-insecure-host` / `UV_INSECURE_HOST` |
| `requirements-files` | requirements or pylock files are produced or consumed | `ls requirements*.txt requirements*.in pylock*.toml`, or a `uv export` step in CI or scripts |

## Rules — Project shape

See [`references/project-shape.md`](./references/project-shape.md).

- **UVP-001** — Use `[dependency-groups]` (PEP 735), not deprecated `[tool.uv.dev-dependencies]`.
- **UVP-002** — Compose groups with `include-group`; never duplicate packages across groups.
- **UVP-003** — `requires-python` is a floor (`">=3.X"`); uv ignores dependency upper bounds, and only a single-minor app pin like `==3.13.*` is an exception.
- **UVP-004** — Git and path deps go in `[tool.uv.sources]`, not raw URLs in `[project.dependencies]` (a raw URL ships in wheel metadata and uv refuses URL deps from registry packages).
- **UVP-005** — `uv init --lib` for libraries, bare `uv init` for apps (packaged since 0.12.0); `--no-package` for a flat layout. _(requires uv>=0.12.0)_
- **UVP-006** — Use a workspace only when members share lockfile resolution; test each member after `uv sync --package <member>` to catch undeclared imports. _(when: workspace)_
- **UVP-007** — Workspace inter-member deps need both `[project.dependencies]` and `[tool.uv.sources]` with `workspace = true`. _(when: workspace)_
- **UVP-008** — Pin a minimum uv version with `[tool.uv] required-version`; newer fields are dropped by old binaries with only a warning.
- **UVP-016** — Declare mutually-exclusive extras/groups with `[tool.uv] conflicts` (bare `{ package = … }` form is preview: package-conflicts). _(when: uv-settings)_
- **UVP-063** — Set `[tool.uv] add-bounds` to control how `uv add` writes constraints. _(when: uv-settings)_ _(requires uv>=0.10.0)_
- **UVP-064** — Bound lockfile platform scope with `environments` / `required-environments`; markers disjoint, macOS baseline with `==`, libc via `minimum-libc-version`. _(when: uv-settings)_
- **UVP-090** — Never embed credentials in git or direct-URL dependencies; use SSH, a credential helper, `.netrc` or `uv auth login`.
- **UVP-091** — Declare `[tool.uv] cache-keys` for build inputs outside `pyproject.toml`, and keep `pyproject.toml` in the list. _(when: packaged)_
- **UVP-092** — Put uv settings at the workspace root, in one file; member settings and a shadowed `[tool.uv]` are ignored. _(when: workspace)_

## Rules — Lockfile

See [`references/lockfile.md`](./references/lockfile.md).

- **UVP-010** — Commit `uv.lock` for **both** apps and libraries.
- **UVP-011** — `--locked` validates lock vs `pyproject.toml`; `--frozen` skips validation (both still install the project — use `--no-install-project` to skip it) — they're not interchangeable.
- **UVP-012** — Use targeted `uv lock --upgrade-package <name>` over blanket `uv lock --upgrade`; a constraint edit or a branch Git dep does not move the lock without `--upgrade-package`.
- **UVP-013** — Never manually edit `uv.lock` (uv refuses to parse a tampered lock); pin transitives with `constraint-dependencies`, overrides only as a last resort. _(when: uv-settings)_
- **UVP-014** — Don't commit `requirements.txt` alongside `uv.lock`; generate it as a build artifact via `uv export`, or if forced, with the `uv-export` pre-commit hook plus a CI diff check. _(when: requirements-files)_
- **UVP-015** — `uv lock --check` (lockfile vs `pyproject.toml`) and `uv sync --check` (env vs lockfile, ≥0.6.10) are composable, not interchangeable — use both at the right gates.
- **UVP-070** — `uv lock --upgrade-group <group>` (≥0.11.4) refreshes one dependency group without touching others. _(requires uv>=0.11.4)_
- **UVP-075** — Set a relative `exclude-newer` (`"7 days"`) as a resolver-side release cooldown, match the Dependabot/Renovate cooldown to it, and opt out an index that has no upload times per index. _(when: uv-settings)_ _(requires uv>=0.9.17)_
- **UVP-086** — Scope pre-releases with `prerelease-package = { foo = "allow" }`, not a global `prerelease = "allow"`. _(when: uv-settings)_ _(requires uv>=0.12.1)_

## Rules — Environments & sync

See [`references/environments.md`](./references/environments.md).

- **UVP-020** — Production sync: `uv sync --locked --no-dev --no-editable`; a partial `--no-install-project` layer is always followed by a full sync.
- **UVP-021** — Run project commands with `uv run`, not a manually activated `.venv`; `uv run` re-checks the lock and environment.
- **UVP-022** — Set `UV_PROJECT_ENVIRONMENT` to an absolute path for one project only, never a system prefix. _(when: env-overrides)_
- **UVP-023** — Configure `default-groups` deliberately; bare `uv sync` installs `dev` unless you pass `--no-dev` or `--no-default-groups`.
- **UVP-024** — PEP 723 scripts: manage deps with `uv add --script` and lock with `uv lock --script`. Inline metadata isolates the script from the project even without `--script`. Use the `uv run --script` shebang, and list scripts in Renovate's `pep723` patterns. _(when: scripts)_
- **UVP-025** — Use named `[[tool.uv.index]]` entries, not the deprecated `index-url`/`extra-index-url`. Keep `first-index`. `default = true` drops PyPI. Credentials are never locked: use credential-free URLs and `UV_INDEX_<NAME>_*`, plus `authenticate = "always"` for indexes that forward to PyPI. _(when: private-index)_
- **UVP-066** — `uv run --with` layers an ephemeral overlay that still sees the project; use `--no-project --isolated` or `uvx` for true isolation.
- **UVP-068** — uv ignores `VIRTUAL_ENV` in projects; pass `--active` to use the activated venv, since there is no env-var form.
- **UVP-077** — In a workspace, bare `uv sync`/`uv run` act on the root only; use `--all-packages` or `--package`. _(when: workspace)_
- **UVP-082** — Behind a TLS-intercepting proxy, trust the corporate CA with `system-certs` (or a complete PEM bundle in `SSL_CERT_FILE`/`SSL_CERT_DIR`); never commit `allow-insecure-host`. _(when: env-overrides)_ _(requires uv>=0.11.0)_
- **UVP-083** — Add missing build dependencies with `[tool.uv.extra-build-dependencies]` instead of `no-build-isolation-package`. _(when: uv-settings)_ _(requires uv>=0.10.0)_
- **UVP-084** — Do not `uv pip install` into a project environment: `uv sync` removes the package but `uv run` keeps it, so the drift hides. Use `uv add`, a group, or `uv run --with`.
- **UVP-085** — Keyring index auth needs `keyring-provider = "subprocess"` and a `keyring` on PATH, installed with its plugin from public PyPI via `uv tool install`, never as a project dependency. _(when: private-index)_

## Rules — CI integration

See [`references/ci.md`](./references/ci.md).

- **UVP-028** — Run `uv audit --locked --preview-features audit-command` in CI to scan the lockfile for known vulnerabilities. _(when: ci)_ _(requires uv>=0.11.3 (preview: audit-command))_
- **UVP-030** — Pin `astral-sh/setup-uv` to a commit SHA with the version tag in a comment. _(when: ci)_
- **UVP-031** — Let `setup-uv` handle caching, never cache `.venv` across runs, and end any job that persists the cache with `uv cache prune --ci`. _(when: ci)_
- **UVP-032** — `uv sync --locked` in CI; bare `uv sync` silently re-resolves. _(when: ci)_
- **UVP-033** — Set `UV_LINK_MODE=copy` for cross-filesystem caches (GitLab CI, BuildKit cache mounts); never `symlink`. _(when: env-overrides)_
- **UVP-065** — Run `uv audit` with SARIF output and centralize ignores in `[tool.uv.audit]`, preferring `ignore-until-fixed`. _(when: ci)_ _(requires uv>=0.11.22 (preview: audit-command))_
- **UVP-069** — Enumerate workspace members with `uv workspace list` in monorepo CI. _(when: workspace)_ _(requires uv>=0.10.0)_
- **UVP-080** — Pin the uv version CI installs (setup-uv `version:`, an exact `required-version`, or a versioned `ghcr.io/astral-sh/uv` image tag); never install latest. _(when: ci)_
- **UVP-081** — Authenticate private GitHub git dependencies in CI with a PAT repository secret plus `gh auth setup-git` after `gh auth login --with-token`. _(when: ci)_

## Rules — Tools

See [`references/tools.md`](./references/tools.md).

- **UVP-040** — Project-workflow tools → `[dependency-groups]`. Personal cross-project CLIs → `uv tool install`. _(when: tools)_
- **UVP-041** — `uvx` for one-shot tool execution: pin with `@<exact>` or `--from '<range>'`, because unpinned reuses a cached or installed version and tool commands ignore the project's `[tool.uv]`, `.python-version` and `requires-python`. _(when: tools)_
- **UVP-042** — `uv tool upgrade --all` is unsafe in CI; pin or declare tools instead. _(when: ci)_
- **UVP-072** — Audit global tools with `uv tool list --outdated` / `--show-python`. _(when: tools)_ _(requires uv>=0.10.10)_
- **UVP-076** — `uv check` runs the locked ty; `uv format` ignores the locked ruff. _(requires uv>=0.11.25 (preview: check-command), uv>=0.8.13 (preview: format-command))_
- **UVP-079** — Vulnerability-scan installed tools with `uv tool audit`. _(when: tools)_ _(requires uv>=0.12.2 (preview: audit-command), uv>=0.12.2 (preview: tool-install-locks))_

## Rules — Python versions

See [`references/python-versions.md`](./references/python-versions.md).

- **UVP-050** — `.python-version` pins the runtime minor; `requires-python` declares the compat floor (uv otherwise takes the first compatible interpreter, so unpinned machines differ); matrix via setup-uv `python-version` or `UV_PYTHON`, setup-python via `python-version-file: .python-version`.
- **UVP-051** — Pin the *minor* version in `.python-version` (`3.12`), not the patch or a uv-only request format.
- **UVP-052** — `UV_PYTHON_DOWNLOADS=never` in air-gapped CI; `manual` when an explicit `uv python install` step provisions Python. _(when: ci)_
- **UVP-053** — `uv version` manages the project version (uv 0.7+); use `uv self version` for the binary.
- **UVP-054** — Resolution strategy for libraries: matrix-test `lowest-direct` and `highest`. _(when: publish)_
- **UVP-067** — Upgrade uv first, then keep managed interpreters patched with `uv python upgrade`; venvs created with an explicit patch are not auto-upgraded. _(requires uv>=0.10.0)_
- **UVP-073** — uv's default managed Python is 3.15 since 0.13.0 — pin explicitly.
- **UVP-093** — Make the interpreter source explicit with `python-preference` (`only-managed` / `only-system`) in CI and images. _(when: ci)_
- **UVP-094** — Give a dependency group its own `requires-python` in `[tool.uv.dependency-groups]` instead of raising the project floor.

## Rules — Building & publishing

See [`references/packaging.md`](./references/packaging.md).

- **UVP-026** — Build the distributions you publish with `uv build --no-sources` (it checks `build-system.requires` only), and smoke-install the wheel with `uv run --isolated --no-project --with dist/*.whl` to catch runtime deps that only `[tool.uv.sources]` can find. _(when: publish)_
- **UVP-027** — Publish to PyPI from GitHub Actions with OIDC trusted publishing: separate build and publish jobs, `id-token: write` only on publish, `enable-cache: false`, `persist-credentials: false`, attestations from `astral-sh/attest-action`, and per-project tokens as the fallback. _(when: publish)_
- **UVP-029** — Use `uv_build` for pure-Python packages, pinned `>=<current>,<next-minor>`, with a dotted `module-name` for namespace packages, never `namespace = true`. _(when: packaged)_
- **UVP-087** — Publish to a non-PyPI index with a `[[tool.uv.index]]` `publish-url` and `uv publish --index <name>`, not a bare `UV_PUBLISH_URL` (failing that, add `--check-url`). _(when: publish)_
- **UVP-088** — Mark internal packages that must never be published with the `Private :: Do Not Upload` classifier (it protects PyPI only). _(when: packaged)_
- **UVP-089** — Declare a `[build-system]` when the project has entry points, is built or published, or sets `tool.uv.package = true`.

## Rules — Migration

See [`references/migration.md`](./references/migration.md).

- **UVP-060** — Migrate with `migrate-to-uv` (poetry / PDM / Hatch / pip-tools) or, for pip, `uv add -r X.in -c X.txt` so old pins become constraints, then diff the resolved versions before committing. _(when: requirements-files)_
- **UVP-061** — `uv export --locked --format requirements.txt --no-dev` (add `--no-editable` when the project is bundled, `--no-emit-project` for dependency-only layers) for downstream consumers; generate, never commit. _(when: requirements-files)_
- **UVP-062** — Prefer `uv export --format pylock.toml` over `requirements.txt` when downstream supports PEP 751 (pip>=26.1); keep `uv.lock` as the project lock. _(when: requirements-files)_
- **UVP-074** — Generate a CycloneDX SBOM with `uv export --format cyclonedx1.5`. _(when: requirements-files)_ _(requires uv>=0.9.11 (preview: sbom-export))_

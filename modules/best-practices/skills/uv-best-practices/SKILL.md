---
name: uv-best-practices
description: Use when working with uv (Astral's Python package and project manager) — `uv sync` / `add` / `lock` / `run` / `tool` / `build` / `publish` / `audit` / `export`, `uvx`, a `uv.lock` or `pylock.toml` file, or a `pyproject.toml` with `[tool.uv]` or `[dependency-groups]`. Covers project shape, lockfile hygiene, workspaces, dependency groups, private registries, Python version pinning, CI, publishing, vulnerability scanning, and migration from pip / poetry / PDM / Hatch. Covers the UVP- rule family. For container-side uv patterns (Dockerfile builds) use containers-best-practices instead.
---

# uv best practices

A curated rule set for using [uv](https://github.com/astral-sh/uv) as
the Python project tool — outside of containers. Container-side uv
rules (`UV-001..UV-008`) cover Dockerfile-specific patterns and live in
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

## How to use the rule index

1. Scan the relevant section(s) below for rule IDs that apply.
2. For each rule, open the corresponding `references/` file and read **only that rule's entry** — they're keyed by ID.
3. Cite the rule ID when explaining a change to the user (e.g. "Switching to dependency groups — UVP-001").

## Rules — Project shape

See [`references/project-shape.md`](./references/project-shape.md).

- **UVP-001** — Use `[dependency-groups]` (PEP 735), not deprecated `[tool.uv.dev-dependencies]`.
- **UVP-002** — Compose groups with `include-group`; never duplicate packages across groups.
- **UVP-003** — `requires-python` is a *floor* (`">=3.X"`), never an upper-bounded range.
- **UVP-004** — Git and path dependencies go in `[tool.uv.sources]`, not as raw URLs in `[project.dependencies]`.
- **UVP-005** — `uv init --lib` for libraries (src/ + build-system); bare `uv init` for apps (flat, `package = false`).
- **UVP-006** — Use a workspace only when members share lockfile resolution; conflicting deps or different Python floors mean you don't want one.
- **UVP-007** — Workspace inter-member deps need *both* `[project.dependencies]` and `[tool.uv.sources]` with `workspace = true`.
- **UVP-008** — Pin a minimum uv version with `[tool.uv] required-version` (≥0.5.14) so all contributors and CI agree on resolver behavior.
- **UVP-016** — Declare mutually-exclusive extras / groups (cpu vs gpu, redis vs memcached) with `[tool.uv] conflicts` (≥0.5.3) so uv forks resolution instead of producing a broken universal lock.
- **UVP-063** — Set `[tool.uv] add-bounds` (stable ≥0.10.0) to control how `uv add` writes version constraints.
- **UVP-064** — Bound lockfile platform scope with `environments` (restrict) or `required-environments` (guarantee wheels).

## Rules — Lockfile

See [`references/lockfile.md`](./references/lockfile.md).

- **UVP-010** — Commit `uv.lock` for **both** apps and libraries.
- **UVP-011** — `--locked` validates lock vs `pyproject.toml`; `--frozen` skips validation **and** skips installing the project package — they're not interchangeable.
- **UVP-012** — Use targeted `uv lock --upgrade-package <name>` over blanket `uv lock --upgrade` in production pipelines.
- **UVP-013** — Never manually edit `uv.lock` — it's fully generated and uv will silently regenerate or error on tampered files.
- **UVP-014** — Don't commit `requirements.txt` alongside `uv.lock`; if downstream tooling needs it, generate as a build artifact via `uv export`.
- **UVP-015** — `uv lock --check` (lockfile vs `pyproject.toml`) and `uv sync --check` (env vs lockfile, ≥0.6.10) are composable, not interchangeable — use both at the right gates.
- **UVP-070** — `uv lock --upgrade-group <group>` (≥0.11.4) refreshes one dependency group without touching others.

## Rules — Environments & sync

See [`references/environments.md`](./references/environments.md).

- **UVP-020** — Production sync incantation: `uv sync --locked --no-dev --no-editable`.
- **UVP-021** — `uv run` over manual `.venv/bin/activate` — it re-checks the lockfile before executing.
- **UVP-022** — Set `UV_PROJECT_ENVIRONMENT` only to **absolute** paths; relative paths in multi-project repos silently target shared/system environments.
- **UVP-023** — Configure `default-groups` deliberately; the default `["dev"]` means bare `uv sync` installs dev dependencies in production.
- **UVP-024** — PEP 723 inline scripts: manage deps via `uv add --script`, lock with `uv lock --script` — and remember `uv run --script` runs isolated from any surrounding project's lockfile.
- **UVP-025** — Configure additional indexes via `[[tool.uv.index]]` with `explicit = true` for private registries; never use `index-strategy = "unsafe-best-match"` (re-introduces dependency-confusion risk).
- **UVP-066** — `uv run --with` builds an ephemeral overlay env (≥0.8.0); add `--isolated`/`uvx --isolated` when project packages must not leak in.
- **UVP-068** — `uv run/sync --active` (or `UV_ACTIVE=1`) makes uv use the *activated* venv instead of silently creating `.venv`.

## Rules — CI integration

See [`references/ci.md`](./references/ci.md).

- **UVP-028** — Run `uv audit` in CI to scan `uv.lock` against the OSV vulnerability database; exits non-zero on findings.
- **UVP-030** — Pin `astral-sh/setup-uv` to a commit SHA with the version tag in a comment.
- **UVP-031** — Let `setup-uv` handle caching (`enable-cache: true`); never cache `.venv/` across runs — Python ABI / OS drift will silently break it.
- **UVP-032** — `uv sync --locked` in CI; bare `uv sync` silently re-resolves on a stale lockfile and ships untested versions.
- **UVP-033** — Set `UV_LINK_MODE=copy` in CI systems with cross-filesystem caches (GitLab, some Docker layered builds) to silence hardlink warnings and avoid mode confusion.
- **UVP-065** — Run `uv audit` with `--output-format sarif` (≥0.11.22) and centralize accepted-risk ignores in `[tool.uv.audit]`, not inline `--ignore` flags.
- **UVP-069** — In monorepo CI, enumerate members with `uv workspace list` (stable ≥0.10.0) instead of hardcoding paths.

## Rules — Tools

See [`references/tools.md`](./references/tools.md).

- **UVP-040** — Tools in *this* project's workflow (`pytest`, `mypy`, `ruff`, `pre-commit`) → `[dependency-groups]`, locked. Personal cross-project CLIs (`cookiecutter`, `httpie`) → `uv tool install`.
- **UVP-041** — `uvx` (= `uv tool run`) for one-shot tool execution; pin the version when correctness matters (`uvx ruff@0.6.9`, not bare `uvx ruff`).
- **UVP-042** — `uv tool upgrade --all` is fine locally but unsafe in CI — silent version drift; declare tools in `[dependency-groups]` or pin via `uvx <tool>@<version>` instead.
- **UVP-072** — Audit global tools with `uv tool list --outdated` (≥0.10.10) and `--show-python` before a Python upgrade.

## Rules — Python versions

See [`references/python-versions.md`](./references/python-versions.md).

- **UVP-050** — `.python-version` pins the runtime; `requires-python` declares the compat floor. They look similar and aren't interchangeable.
- **UVP-051** — Pin the *minor* version in `.python-version` (`3.12`), not the patch (`3.12.7`) — patch upgrades are transparent; minor changes affect resolution.
- **UVP-052** — `UV_PYTHON_DOWNLOADS=never` in network-restricted CI — surfaces "Python not found" instead of a cryptic network error.
- **UVP-053** — `uv version` (≥0.7.0) manages the *project* version, not uv's own; outside a project it is a **hard error** since 0.8.0. Use `uv self version` for the binary.
- **UVP-054** — For libraries, matrix CI on `--resolution lowest-direct` and `--resolution highest` to catch implicit floor violations and upper-bound rot.
- **UVP-067** — Keep managed interpreters patched with `uv python upgrade` (stable ≥0.10.0); it auto-upgrades venvs on the old patch.
- **UVP-073** — uv's default managed Python is **3.14** since 0.9.0 — pin explicitly with `uv python pin` rather than relying on the default.

## Rules — Building & publishing

See [`references/packaging.md`](./references/packaging.md).

- **UVP-026** — Pre-publish sanity check: `uv build --no-sources` to verify the wheel doesn't accidentally depend on `[tool.uv.sources]` config that doesn't ship.
- **UVP-027** — Publish from GitHub Actions via PyPI OIDC trusted publishing (stable since uv 0.6.0) — no `UV_PUBLISH_TOKEN`, auto-uploaded PEP 740 attestations.
- **UVP-029** — Use the native `uv_build` PEP 517 backend (the **default** for `uv init --lib`/`--package` since uv 0.8.0) for pure-Python packages — 10–35x faster than hatchling / setuptools.
- **UVP-071** — `uv_build` supports PEP 794 `import-names` (≥0.11.17) for packages whose import name differs from the distribution name.

## Rules — Migration

See [`references/migration.md`](./references/migration.md).

- **UVP-060** — Use `astral-sh/migrate-to-uv` (or `uvx migrate-to-uv`) for poetry / pip-tools / PDM / Hatch projects; *manually verify* the resolved versions diff — resolver drift between Poetry and uv has shipped wrong packages to production.
- **UVP-061** — `uv export --format requirements.txt --no-hashes --no-dev -o requirements.txt` for downstream consumers (Lambda layers, deploy targets that need it) — generate in CI, don't commit.
- **UVP-062** — Prefer `uv export --format pylock.toml` (PEP 751, ≥0.6.15) over `requirements.txt` when the downstream tool supports it; never replace `uv.lock` with `pylock.toml` (the format can't represent uv's full graph).
- **UVP-074** — Generate a CycloneDX SBOM with `uv export --format cyclonedx` (≥0.9.11) for supply-chain compliance, separate from the lockfile.

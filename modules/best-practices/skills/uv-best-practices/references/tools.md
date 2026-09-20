# UVP tools rules

Detailed entries for `UVP-040..UVP-042`. Covers `uv tool install` vs
`uv add --dev` vs `uvx`, version pinning, the "works locally, fails
in CI" antipattern from global tools, and the `uv tool upgrade --all`
trap.

Citations point at the [uv tools guide](https://docs.astral.sh/uv/concepts/tools/)
and the [uv tools concepts](https://docs.astral.sh/uv/guides/tools/).

---

## UVP-040 — Project-context tools → `uv add --dev`. Standalone CLIs → `uv tool install`

**What.** Pick the install path by whether the tool needs to see your
project:

| Tool category | Examples | Install via |
|---|---|---|
| Operates on this project's code; needs to import / introspect it | `pytest`, `mypy`, `pyright`, `coverage`, project-bound `ruff` config | `uv add --dev <tool>` |
| Standalone CLI used across many projects, no project-import need | `pre-commit`, `cookiecutter`, `pipx` (the tool itself), `httpie` | `uv tool install <tool>` |

**Why.** This is the **single most common "works locally, fails in
CI"** cause for uv projects:

- Developer runs `uv tool install ruff` once on their laptop. `ruff` lands in `~/.local/share/uv/tools/ruff/` with a `~/.local/bin/ruff` shim. Works fine.
- CI clones the repo and runs `uv sync --locked` followed by `uv run ruff check .`. `ruff` is not in the project's lockfile — it was installed *globally* on the developer's machine. CI fails: "ruff: command not found." The developer says "works on my machine."

Same failure for any team member: a second developer clones the
repo, `uv sync`, `uv run ruff check .` — fails. They have to know
to `uv tool install ruff` separately, with no documentation
prompting them to.

The fix: any tool that's part of the project's *expected workflow*
(linter the team uses, type-checker, test runner) goes in
`[dependency-groups]` so the lockfile pins it and everyone gets the
same version with one `uv sync`.

Standalone CLIs are different — `pre-commit` literally manages its
*own* hook environments separately from any project venv, so
installing it as a project dep would be weird. `cookiecutter` is
invoked once when scaffolding a new project. Those legitimately
belong in `uv tool install` (or `uvx`, see UVP-041).

**How.**

```bash
# project-context tools — pinned in pyproject.toml + uv.lock
uv add --dev pytest pytest-cov ruff mypy
# now `uv run pytest` and `uv run ruff check .` work everywhere

# standalone CLIs — global install, version-pinned
uv tool install 'pre-commit==4.0.0'
uv tool install 'cookiecutter==2.6.0'
```

In CI:

```yaml
# project-context tools work because they're in the lockfile
- run: uv sync --locked --dev
- run: uv run pytest
- run: uv run ruff check .
- run: uv run mypy src/

# standalone CLIs need explicit install in CI (or use uvx, see UVP-041)
- run: uv tool install pre-commit
- run: pre-commit run --all-files
```

A useful self-check: ask "if a new contributor clones this repo,
runs `uv sync`, can they run all the project commands they're
supposed to?" If the answer requires "first they have to install
ruff globally," ruff is in the wrong place.

**When NOT to apply.** Genuinely user-level utilities the *human*
uses across many projects (`httpie`, `ranger`, `ipython` for ad-hoc
shells) — those belong in `uv tool install` because they're not
tied to any one project. The rule targets project-scoped tools that
masquerade as global.

---

## UVP-041 — `uvx` for one-shot tool execution; pin the version when correctness matters

**What.** `uvx` (= `uv tool run`) executes a tool in a temporary
isolated environment without installing it. For one-shot or
infrequent use:

```bash
uvx ruff check .                    # ad-hoc — fetches latest
uvx 'ruff==0.6.9' check .           # pinned — reproducible
uvx 'ruff@0.6.9' check .            # equivalent shorthand
```

**Why.** Three real considerations:

1. **`uvx ruff` without a version pin fetches the *latest* `ruff` every cold-cache invocation.** A linter version bump that lands while you're not looking can break CI without any source change. For correctness-critical tools (linters that gate merges, formatters that produce diffs), pin.
2. **`uvx` doesn't pollute global tool state.** Compared to `uv tool install`, there's no entry in `~/.local/share/uv/tools/` and no shim in `~/.local/bin/`. Good for genuinely one-shot use (`uvx cookiecutter gh:org/template`), and avoids the "I installed it once and now I have a stale version everywhere" problem.
3. **`uvx` runs in isolation — it doesn't see your project.** If you `uvx pytest`, it won't import your project's source. This is the right behavior for project-agnostic tools but the wrong behavior for project-context tools (UVP-040). The uv docs are explicit: "If you are running a tool in a project and the tool requires that your project is installed, you'll want to use `uv run` instead of `uvx`." ([uv tools guide](https://docs.astral.sh/uv/guides/tools/))

**How.**

```bash
# one-shot scaffolding
uvx cookiecutter@2.6.0 gh:cookiecutter/cookiecutter-pypackage

# CI lint — pinned for reproducibility, no install step needed
uvx 'ruff==0.6.9' check .
uvx 'ruff==0.6.9' format --check .

# don't accidentally use uvx for project tools:
uvx pytest                          # WRONG — runs in isolation, can't import project
uv run pytest                       # RIGHT — runs in project venv
```

In CI workflows where `uvx` is the right call:

```yaml
# Lint with explicit version pin (the version lives in your config, not in someone's tool dir)
- run: uvx 'ruff==0.6.9' check .
- run: uvx 'ruff==0.6.9' format --check .
```

A pattern that combines the two: declare the tool version in the
project's `[tool.uv]` `constraint-dependencies` so it's centralized
even when invoked via `uvx`:

```toml
[tool.uv]
constraint-dependencies = ["ruff==0.6.9"]
```

```bash
uvx ruff check .   # constraint pulls in 0.6.9
```

**When NOT to apply.** Tools that need to see your project's source
(use `uv run`, UVP-021). Tools that are invoked frequently enough
that the cold-cache fetch cost matters (use `uv tool install` with a
pinned version).

### uv 0.7.0 behavior change: `uvx foo` errors on missing command

Prior to uv 0.7.0, `uvx foo` would silently fall back to a `foo`
binary on `PATH` if the package didn't expose a `foo` entry point.
This produced bizarre debugging sessions ("why is `uvx pre-commit`
running my system pre-commit?"). uv 0.7.0 changed this to a hard
error: if the installed package doesn't ship a `foo` command, `uvx
foo` exits non-zero with a clear message. The `--from` flag remains
the escape hatch when the binary name differs from the package
name (`uvx --from python-lsp-server pylsp`). Pre-0.7 uv binaries
still have the old silent-fallback behavior; pin via UVP-008.

---

## UVP-042 — `uv tool upgrade --all` is unsafe in CI; pin or declare tools instead

**What.** `uv tool upgrade --all` is a *human convenience* command —
fine to type at a shell, dangerous to put in a CI step. CI's job is
reproducibility; "upgrade everything to whatever's latest on PyPI"
is the opposite of that. Use one of two reproducible alternatives
instead:

1. **Project tools in `[dependency-groups]`** (UVP-040). Locked, versioned, the same on every run.
2. **Standalone CLIs invoked via `uvx <tool>@<exact-version>`** (UVP-041). No persistent install state; the version pin is in CI config, not in a tool dir.

Use `uv tool list --show-with` (added in uv 0.7.3) to audit existing
tool environments before deciding what to migrate.

**Why.** `uv tool upgrade --all` in CI produces silent version drift
across runs that's invisible until something breaks:

1. **Same workflow file, different tool versions.** Two CI runs of the same workflow, an hour apart, can install different versions of `pre-commit`, `cookiecutter`, or anything else under `uv tool`. When run #2 fails and run #1 passed, "what changed?" is unanswerable from the git diff alone — the diff is empty.
2. **Persistent state across runs.** `uv tool install` writes to `~/.local/share/uv/tools/`. On a self-hosted runner that doesn't wipe between jobs, `uv tool upgrade --all` mutates global state visible to *every* subsequent job. Cross-pipeline pollution.
3. **Bypasses the lockfile.** Tools installed via `uv tool` don't appear in `uv.lock`. So the project's "what versions of what" record explicitly excludes them. Anything you want reproducible needs to be either in the lockfile (groups) or pinned at the call site (uvx with `@version`).

**How.**

```bash
# audit what's installed (uv 0.7.3+; --show-with reveals constraint-deps)
uv tool list --show-with

# pattern 1: migrate project tools to a group
uv add --group dev pytest ruff mypy
# remove the global installs
uv tool uninstall pytest ruff mypy

# pattern 2: pin standalone CLIs at the call site
# (in your CI yml, replace `uv tool upgrade --all && pre-commit run ...`)
uvx 'pre-commit@4.0.0' run --all-files
uvx 'cookiecutter@2.6.0' gh:cookiecutter/cookiecutter-pypackage
```

Local-only upgrade pattern (for the human who wants `pre-commit`
fresh on their laptop):

```bash
# perfectly fine locally — just not in CI
uv tool upgrade --all
```

If you genuinely need a refresh step in CI (e.g. a scheduled job
that opens a PR with new tool versions), do it explicitly as part of
the PR's own pinning workflow:

```yaml
# weekly tool-refresh job — opens PR with new pinned versions
- name: Refresh tool pins
  run: |
    new_version="$(uvx pre-commit --version | awk '{print $2}')"
    sed -i "s|pre-commit@[^']*|pre-commit@${new_version}|g" .github/workflows/*.yml
    # then commit + open PR
```

**When NOT to apply.** Throwaway personal CI for a hobby repo where
reproducibility doesn't matter. Even then, the cost of pinning is
one line per tool; the benefit is non-zero.

---

## UVP-072 — Audit global tools with `uv tool list --outdated` / `--show-python`

**What.** Two flags make `uv tool list` useful for maintenance:
`--outdated` (uv 0.10.10) shows which globally-installed tools have newer
releases on PyPI, and `--show-python` (uv 0.9.2) shows which interpreter
each tool's environment was built with.

**Why.** Without `--outdated`, the only way to learn a tool is stale is
to run `uv tool upgrade` and see if anything moves. Without
`--show-python`, tools installed before a Python minor upgrade keep
silently running on the old interpreter — `--show-python` reveals which
ones need `uv tool install --reinstall` to rebuild against the new
Python.

**How.**

```bash
uv tool list --outdated       # which global tools have updates?
uv tool list --show-python    # which interpreter does each use?
uv tool install --reinstall pre-commit   # rebuild against current Python
```

**When NOT to apply.** CI environments that install tools per-run (via
`uv tool install` in a step or `uvx`) — this is a local-developer
maintenance rule, not a CI one.

---

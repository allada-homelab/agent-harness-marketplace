# UVP CI integration rules

Detailed entries for `UVP-028` and `UVP-030..UVP-039`. Covers GitHub
Actions integration, lockfile-driven vulnerability auditing,
caching strategy, lockfile enforcement in CI, and cross-filesystem
mount issues (GitLab, Docker).

Citations point at the [uv GitHub Actions guide](https://docs.astral.sh/uv/guides/integration/github/),
the [setup-uv action repo](https://github.com/astral-sh/setup-uv),
and the [uv GitLab guide](https://docs.astral.sh/uv/guides/integration/gitlab/).

For container builds specifically, also see
`containers-best-practices/references/uv-python.md` (rules `UV-001..UV-008`).

---

## UVP-030 — Pin `astral-sh/setup-uv` to a commit SHA with the version tag in a comment

**What.** When using GitHub Actions, pin the action to a commit hash,
not a floating tag. Add a comment with the tag for human readability:

```yaml
- uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
```

**Why.** This is a generic GitHub Actions supply-chain rule that
applies to *all* third-party actions, including `setup-uv`:

1. **Tag immutability isn't enforced.** A maintainer (or an attacker who compromises maintainer credentials) can move `v8.1.0` to a different commit. Your `@v8.1.0` pin re-resolves to the new commit on the next CI run. Several high-profile supply-chain attacks have used this vector (`tj-actions/changed-files` in 2025 is the canonical example).
2. **`@main` / `@master` / `@v8` is even worse.** Those move on every push to those refs. A breaking change in upstream silently breaks your CI without any change on your side.

Pinning to a commit SHA makes the action immutable. The tag comment
keeps human reviewers oriented to "what version am I looking at."
Dependabot / Renovate both understand this pattern and can update the
SHA + comment together.

**How.**

```yaml
# .github/workflows/test.yml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v5.0.0
      - uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
        with:
          enable-cache: true
          python-version: "3.12"
      - run: uv sync --locked --all-extras --dev
      - run: uv run pytest
```

To get the SHA for a tag:

```bash
# v8.2.0 is the current latest; resolve whichever tag you're pinning
gh api repos/astral-sh/setup-uv/git/refs/tags/v8.2.0 \
  --jq '.object.sha'
```

Or in the GitHub UI: click the tag, copy the commit hash.

**When NOT to apply.** Throwaway personal projects where supply-chain
attack risk is low. Even there, the cost of a SHA pin is one line of
config; the cost of a compromised CI run can be high.

---

## UVP-031 — Let `setup-uv` handle caching; never cache `.venv` across runs

**What.** Use the `setup-uv` action's built-in caching:

```yaml
- uses: astral-sh/setup-uv@<sha> # v8.1.0
  with:
    enable-cache: true                # default is "auto"; explicit is clearer
```

The action caches `~/.cache/uv` (the wheel/source-dist cache), keyed
on hashed `**/uv.lock`, `**/pyproject.toml`, and `**/requirements*.txt`
contents. It runs `uv cache prune --ci` in post-run to keep the
cache lean (strips pre-built wheels that are cheap to re-download,
keeps source-built wheels that are expensive).

Do **not** add `actions/cache` on top of this for the uv directory —
duplicated work. And **never** cache `.venv/` across runs.

**Why.**

1. **`.venv/` is architecture-specific.** A venv built on `ubuntu-latest` (Ubuntu 24.04 / glibc N) restored to a different runner image (or, worse, a self-hosted runner with a different libc) has compiled wheels that segfault or fail to import at runtime. The cache hit produces a "working" environment that crashes on use.
2. **The lockfile drives reproducibility, not the venv.** If the cache is the uv wheel cache + the lockfile, then `uv sync --locked` recreates the venv deterministically. Caching the venv itself adds nothing the lockfile + cache don't already provide, and adds the segfault risk above.
3. **`setup-uv` knows the right cache key.** Hand-rolled `actions/cache` setups commonly key on `pyproject.toml` (changes too rarely) or `requirements.txt` (which you shouldn't have — see UVP-014). The action keys on `uv.lock`, which is what actually drives resolution.

**How.**

```yaml
# minimal correct shape
- uses: astral-sh/setup-uv@<sha> # v8.1.0
  with:
    enable-cache: true
    python-version: "3.12"
- run: uv sync --locked
- run: uv run pytest

# matrix across Python versions — cache stays per-version automatically
strategy:
  matrix:
    python-version: ["3.11", "3.12", "3.13"]
steps:
  - uses: actions/checkout@<sha>
  - uses: astral-sh/setup-uv@<sha> # v8.1.0
    with:
      python-version: ${{ matrix.python-version }}
      enable-cache: true
  - run: uv sync --locked
  - run: uv run pytest
```

If you must use `actions/cache` manually (non-GitHub CI, or for an
expert reason), use this key shape:

```yaml
key: uv-${{ runner.os }}-${{ matrix.python-version }}-${{ hashFiles('uv.lock') }}
restore-keys: |
  uv-${{ runner.os }}-${{ matrix.python-version }}-
```

`runner.os` matters because wheel ABIs differ by OS. `matrix.python-version`
matters because Python ABI changes between minor versions.

**When NOT to apply.** Self-hosted runners with no network access —
caching is moot because there's nothing to cache against. In that
case, populate a local PyPI mirror via `[[tool.uv.index]]` and disable
downloads (UVP-052).

---

## UVP-032 — `uv sync --locked` in CI; bare `uv sync` silently re-resolves

**What.** In CI, every `uv sync` invocation gets the `--locked` flag:

```yaml
- run: uv sync --locked              # good — fails loudly if lockfile is stale
- run: uv sync --locked --all-extras --dev  # also good — explicit groups
- run: uv sync                       # BAD — silently re-resolves if pyproject drifted
```

**Why.** This is the most common CI footgun in uv projects (open
issue [uv#12372](https://github.com/astral-sh/uv/issues/12372)
requests `--locked` become the default for exactly this reason).

The failure mode is sneaky:

1. A developer adds a dependency to `pyproject.toml`.
2. They forget to run `uv lock` (or run `uv add` but the lockfile update doesn't make it into the commit).
3. CI runs `uv sync` (no `--locked` flag).
4. uv sees `pyproject.toml` has changed, **silently regenerates the lockfile in CI**, installs whatever the resolver picked, and runs tests against that.
5. Tests pass. The PR merges. The committed `uv.lock` is stale.
6. The next developer's `uv sync --locked` locally fails with "lockfile is out of date." Production deploys, depending on the deploy pipeline's flags, may install yet a third version.

`--locked` catches the missing-lock-update at step 4 by failing the
CI job. Loudly. Which is what you want.

**How.**

```yaml
# every CI step that touches the environment
- run: uv sync --locked --dev
- run: uv run pytest

# verify the lockfile is current as a separate explicit step (optional, extra-strict)
- name: Verify lockfile is current
  run: uv lock --check
```

`uv lock --check` does the validation without syncing — useful when
you want to gate "is the lockfile current" as a pre-step before
spending time on the rest of the install.

For multi-stage workflows (lint job + test job + build job, each
syncing), use `--locked` on every sync. The validation is cheap.

**When NOT to apply.** Local dev shells where you genuinely want
auto-relock when iterating on pyproject.toml. CI is *never* one of
those cases.

---

## UVP-033 — Set `UV_LINK_MODE=copy` for cross-filesystem caches

**What.** When the uv cache directory and the project venv are on
different filesystems (or different mount points), set:

```bash
export UV_LINK_MODE=copy
```

or in CI config:

```yaml
env:
  UV_LINK_MODE: "copy"
```

**Why.** uv's default `link-mode` is `hardlink` — it hardlinks wheel
contents from the cache directly into the venv, which is fast and
cheap on disk. Hardlinks require both sides to be on the *same*
filesystem; cross-filesystem hardlinks fall back to copy *with a
warning*:

```
warning: Failed to hardlink files; falling back to full copy.
This may lead to degraded performance.
If the cache and target directories are on different filesystems,
hardlinking may not be supported.
Set `export UV_LINK_MODE=copy` or use `--link-mode=copy` to suppress this warning.
```

The warning isn't *wrong* — performance is genuinely degraded — but
in CI it spams every install step. Two real cases where this comes up:

1. **GitLab CI.** The cache directory and the build directory are on different volumes by default. Every `uv sync` produces a wall of warnings, drowning out real errors. ([uv GitLab guide](https://docs.astral.sh/uv/guides/integration/gitlab/))
2. **Docker BuildKit cache mounts.** `RUN --mount=type=cache,target=/root/.cache/uv` puts the cache on a separate volume from the layer being written. Same issue — falls back to copy with warnings on every install.

Setting `UV_LINK_MODE=copy` makes the copy explicit, suppresses the
warning, and matches what's actually happening anyway.

**How.**

```yaml
# GitLab CI
variables:
  UV_LINK_MODE: "copy"
  UV_CACHE_DIR: ".uv-cache"

test:
  image: ghcr.io/astral-sh/uv:0.11.16-python3.12-trixie-slim
  cache:
    key:
      files: [uv.lock]
    paths: [.uv-cache]
  script:
    - uv sync --locked --dev
    - uv run pytest
    - uv cache prune --ci
```

```dockerfile
# Dockerfile with BuildKit cache mount
ENV UV_LINK_MODE=copy
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev
```

(This Dockerfile pattern also appears in the container-side
`UV-002` and `UV-003` rules.)

**When NOT to apply.** Local development on a single filesystem (the
common case for macOS / Linux dev machines). Don't set
`UV_LINK_MODE=copy` there — hardlinks are faster, and the warning
won't fire.

---

## UVP-028 — Run `uv audit` in CI to scan the lockfile for known vulnerabilities

**What.** `uv audit` queries the
[OSV vulnerability database](https://osv.dev/) (default) for every
package version in `uv.lock` and reports known CVEs / advisories.
Exit code is non-zero when findings are present, which makes it a
proper CI gate. Add it as a step alongside lint and tests.

`uv audit` is still **experimental**: uv prints "`uv audit` is
experimental and may change without warning. Pass `--preview-features
audit-command` to disable this warning." Pass that flag to acknowledge
it, and pin the uv version in CI so a flag or output change arrives as a
reviewed bump. Pass `--locked` too: without it, audit re-resolves and
may rewrite `uv.lock` instead of auditing the committed one, while
`--locked` fails if the lockfile is stale.

```bash
uv audit --locked --preview-features audit-command                         # non-zero on findings
uv audit --locked --preview-features audit-command --output-format json    # tooling / annotation
uv audit --locked --preview-features audit-command --output-format sarif   # GitHub code scanning
uv audit --locked --preview-features audit-command --no-dev                # skip the dev group
uv audit --locked --preview-features audit-command --ignore GHSA-xxxx-yyyy-zzzz  # accepted risk
```

**Why.** A lockfile pinned today drifts into vulnerability over time —
PyPI publishes a CVE on `requests==2.31.0`, but your locked version
doesn't change until someone runs `uv lock --upgrade-package`. Without
an audit step, the only signal is a dependency-bot PR ("might want to
update this") or a security incident. `uv audit` makes "is my
lockfile shipping known vulnerabilities" a yes/no question with an
exit code:

1. **It runs against the lockfile, not the running environment.** Most pip-side scanners (`pip-audit`, `safety`) iterate the installed packages. `uv audit` reads `uv.lock` directly, so it works pre-install — fast, deterministic, and catches issues before you've spent the time syncing.
2. **It's first-party.** Cross-tool format drift between `uv.lock` and `requirements.txt` (UVP-014) means a generic scanner against an exported `requirements.txt` can miss URL deps, workspace members, or markers that uv resolved correctly. Native uv tooling sees the full graph.
3. **Source / format are configurable.** `--service-format osv` is the default; enterprises with private vulnerability feeds can point at their own service via `--service-url`. The `--ignore-until-fixed` flag accepts a CVE *only as long as no fix exists upstream* — once a patched version ships, the allowlist entry expires and the check fails again, forcing an upgrade.

This rule is uv-side. For broader-spectrum scanning (including the
running container, system packages, SBOM generation), see PY-077
(`pip-audit`) in `python-best-practices` — they complement, not
replace each other.

**How.**

```yaml
# .github/workflows/audit.yml
name: Audit
on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "0 6 * * *"          # daily, surfaces newly-disclosed CVEs
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>
      - uses: astral-sh/setup-uv@<sha> # v8.1.0
        with:
          enable-cache: true
      # No sync needed — audit reads uv.lock directly
      - run: uv audit --locked --preview-features audit-command --no-dev
```

For accepted-risk findings (e.g. a CVE that only affects a code path
you don't use), centralize the allowlist in `pyproject.toml` rather
than scattering `--ignore` flags across CI files:

```toml
[tool.uv.audit]
ignore = [
  "GHSA-xxxx-yyyy-zzzz",   # only triggers in code path we don't use; reviewed YYYY-MM-DD
]
ignore-until-fixed = [
  "CVE-2025-12345",        # accepted only while no fix exists upstream
]
```

For machine-consumable output, use `--output-format sarif` for GitHub
code scanning (UVP-065) or `--output-format json` for custom dashboards.

**When NOT to apply.** Two narrow cases:

1. **Air-gapped CI with no OSV access.** Point `--service-url` at an internal mirror, or run the audit on a network-attached runner that publishes findings into your air-gapped pipeline. Don't silently skip it.
2. **Repos consumed only as templates / scaffolding** that never ship deployable artifacts. The vulnerability set in a template repo's lockfile doesn't matter the same way; the audit cost is overhead.

---

## UVP-065 — Run `uv audit` with SARIF output and centralize ignores in `[tool.uv.audit]`

**What.** `uv audit` (extends UVP-028) scans `uv.lock` against the OSV
database without syncing the environment. As of uv 0.11.22 it can emit
SARIF for GitHub code scanning. Put accepted-risk ignores in
`[tool.uv.audit]` in `pyproject.toml` — not as inline `--ignore` flags in
CI commands.

**Why.** Scattering `--ignore GHSA-xxxx` across CI YAML hides the
accepted-risk list: no one can see which advisories were waived, when, or
by whom, and it can't be diffed in review. `pyproject.toml` centralizes
the list where it's version-controlled and reviewable next to the project
that accepts the risk. `ignore-until-fixed` is designed to expire once a
patched version ships, so the gate re-fires automatically instead of
silently masking a now-fixable CVE.

**How.**

```yaml
# `uv audit` writes SARIF to stdout (it has no -o flag) and exits 1 on findings,
# so upload with always() or the report is lost exactly when it matters.
- run: uv audit --locked --preview-features audit-command --no-dev --output-format sarif > audit.sarif
- uses: github/codeql-action/upload-sarif@<sha>
  if: always()
  with: { sarif_file: audit.sarif }
```

```toml
[tool.uv.audit]
ignore = ["GHSA-xxxx-yyyy-zzzz"]        # reviewed; only affects unused path
ignore-until-fixed = ["CVE-2026-12345"] # no fix yet; expires when one ships
```

**When NOT to apply.** Air-gapped CI with no OSV access — point
`--service-url` at an internal mirror, or accept that audit needs
network. Template/scaffolding repos that are never deployed don't need a
gate.

---

## UVP-069 — Enumerate workspace members with `uv workspace list` in monorepo CI

**What.** `uv workspace list` (stable since uv 0.10.0; `--output-format
json` for scripting) lists every member of a uv workspace with name and
path. Use it to drive per-member CI matrices instead of hardcoding the
member list.

**Why.** A hardcoded member list in CI drifts the moment someone adds a
package to the workspace — the matrix silently skips the new member
(unbuilt, untested) until somebody notices. `uv workspace list` derives
the set from `[tool.uv.workspace]` globs, so it can't fall out of sync.

**How.**

```bash
for m in $(uv workspace list --output-format json | jq -r '.[].name'); do
  echo "::group::$m"; uv run --package "$m" pytest; echo "::endgroup::"
done
```

**When NOT to apply.** A workspace whose CI just syncs and tests the root
(`uv sync --locked` covers all members in one job) doesn't need
enumeration — this is for *per-member* build/test/publish steps.

---

# UVP packaging rules

Detailed entries for `UVP-026..UVP-029`. Covers building wheels with
`uv build`, publishing to PyPI via `uv publish` (including OIDC
trusted publishing), and the native `uv_build` backend.

Citations point at the [uv package guide](https://docs.astral.sh/uv/guides/package/)
and the [uv_build backend docs](https://docs.astral.sh/uv/concepts/projects/build-backend/).

For lockfile export to `requirements.txt` / `pylock.toml`, see
[`migration.md`](migration.md) (UVP-061, UVP-062). For the project
shape that determines what gets built, see
[`project-shape.md`](project-shape.md) (UVP-005, UVP-008, UVP-016).

---

## UVP-026 — Pre-publish sanity check: `uv build --no-sources`

**What.** Before publishing a wheel to PyPI, build it once with
`--no-sources` to verify it doesn't accidentally depend on anything
declared in `[tool.uv.sources]` — git deps, local paths, or named
private indexes.

```bash
# normal local build — uses [tool.uv.sources]
uv build

# the sanity check — pretends [tool.uv.sources] doesn't exist
uv build --no-sources
```

If `--no-sources` fails to resolve a dependency, the wheel you were
about to publish would have broken for every consumer.

**Why.** `[tool.uv.sources]` is uv-specific local metadata. It tells
*your* uv where to find git repos, path siblings, and private indexes
during development — but **it doesn't ship in the published wheel**.
Wheels carry only the normalized PEP 508 dependency specs from
`[project.dependencies]`.

Concrete failure mode:

1. A library declares `dependencies = ["internal-lib"]` in `[project]` and `internal-lib = { git = "ssh://..." }` in `[tool.uv.sources]`. Locally, `uv build` resolves via the git URL and the wheel builds fine.
2. The wheel is published. The wheel metadata says `Requires-Dist: internal-lib` — no URL, no source hint, just the name.
3. A consumer `pip install`s the package. pip looks up `internal-lib` on PyPI and either fails ("no version found") or — worse — installs a *typosquatted* package with the same name.

Step 3 is exactly the dependency-confusion attack vector that UVP-025
discusses on the *consumer* side. `--no-sources` catches it on the
*producer* side: it forces resolution to use only what's declared in
`[project.dependencies]` plus the indexes a consumer would see, which
is what the published wheel actually requires of its users.

See the [uv package docs on `--no-sources`](https://docs.astral.sh/uv/guides/package/#preparing-your-package-for-publishing).

**How.**

```bash
# CI release workflow — run as a gate before publishing
- name: Verify build with no sources
  run: uv build --no-sources
- name: Build for publish
  run: uv build
- name: Publish
  run: uv publish
```

```yaml
# Or as a separate "release-readiness" check on every PR to main
jobs:
  release-readiness:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>
      - uses: astral-sh/setup-uv@<sha> # v8.1.0
        with: { enable-cache: true }
      - name: Build without [tool.uv.sources]
        run: uv build --no-sources
        # if this fails, a published wheel would be broken
```

If `--no-sources` does fail, fix the underlying issue rather than
bypassing the check. The fix is typically one of:

- **Convert a git dep to a published dep.** Publish `internal-lib` to your private PyPI; depend on it normally. Document the private index for consumers (UVP-025).
- **Vendor the dep.** For small utilities, copy the code into your package.
- **Make the dep optional.** Move it from `[project.dependencies]` into an optional extra that only consumers who have access to the private index will install.

**When NOT to apply.** Internal-only packages that won't be published
to public PyPI — when your "consumers" are the same team that has
access to the private indexes you've configured. The rule kicks in
the moment a package is published anywhere external consumers can
install from.

---

## UVP-027 — Publish from GitHub Actions via OIDC trusted publishing

**What.** When publishing to PyPI from GitHub Actions, use
[PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/) —
OIDC-based authentication that exchanges the GitHub Actions identity
token for a short-lived PyPI upload token. No `UV_PUBLISH_TOKEN`
secret, no API token rotation. `uv publish` auto-detects the GitHub
Actions OIDC context and uses it.

OIDC trusted publishing graduated from preview to stable in uv 0.6.0.

```yaml
# .github/workflows/publish.yml
name: Publish
on:
  release:
    types: [published]
jobs:
  publish:
    runs-on: ubuntu-latest
    environment: pypi              # the trusted-publisher environment, configured on PyPI
    permissions:
      id-token: write              # required for OIDC token minting
      contents: read
    steps:
      - uses: actions/checkout@<sha>
      - uses: astral-sh/setup-uv@<sha> # v8.1.0
      - run: uv build --no-sources
      - run: uv build
      - run: uv publish            # no token, no auth flags — OIDC handles it
```

See the [uv publish guide](https://docs.astral.sh/uv/guides/package/#publishing-your-package).

**Why.** Three concrete benefits over long-lived API tokens:

1. **No secret to rotate or leak.** A PyPI API token committed by mistake (or exposed in a build log) is a publish-as-you incident until revoked. OIDC tokens are minted at job-run time and expire in minutes; there's nothing in the repo or workflow secrets to steal.
2. **Cryptographically bound to the workflow.** PyPI verifies the OIDC token came from the specific `<org>/<repo>` and the specific workflow file the project has configured as a trusted publisher. A fork can't publish to your project even if it spoofs the workflow shape; the audience check fails.
3. **PEP 740 attestations are auto-uploaded.** When `uv publish` runs inside GitHub Actions with OIDC, uv builds and uploads [PEP 740 provenance attestations](https://peps.python.org/pep-0740/) alongside the wheel — cryptographic proof of which workflow produced the artifact. This shows up as a "Verified" badge on PyPI and is consumable by downstream supply-chain tooling.

The setup on PyPI is one-time: on the project's "Publishing" tab,
add a "trusted publisher" entry naming the GitHub org, repo,
workflow filename, and (optionally) the environment. Future
`uv publish` runs from that workflow Just Work.

**How — full workflow.**

```yaml
# .github/workflows/publish.yml
name: Publish to PyPI

on:
  push:
    tags: ["v*"]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>
      - uses: astral-sh/setup-uv@<sha> # v8.1.0
        with: { enable-cache: true }
      - run: uv build --no-sources
      - run: uv build
      - uses: actions/upload-artifact@<sha>
        with:
          name: dist
          path: dist/

  publish:
    needs: build
    runs-on: ubuntu-latest
    environment: pypi              # protected env, requires reviewer approval
    permissions:
      id-token: write              # mint the OIDC token
    steps:
      - uses: actions/download-artifact@<sha>
        with: { name: dist, path: dist/ }
      - uses: astral-sh/setup-uv@<sha> # v8.1.0
      - run: uv publish            # picks up OIDC from the runner
```

For registries that don't support PEP 740 attestations (some private
mirrors), opt out:

```bash
uv publish --no-attestations
```

For non-GitHub Actions runners (GitLab, self-hosted), trusted
publishing is still possible but the OIDC flow differs — see
[PyPI's GitLab guide](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

**When NOT to apply.** Two cases:

1. **Publishing to a private registry that doesn't support OIDC.** Stay on `UV_PUBLISH_TOKEN` / `--token`, rotate regularly, store in the runner's secret manager (never in the repo).
2. **One-off manual publishes from a developer's laptop.** OIDC requires the GitHub Actions OIDC issuer; a laptop has no such token. Use a scoped API token for the rare manual publish, and prefer to make publishing CI-only.

---

## UVP-029 — `uv_build` backend for pure-Python packages

**What.** uv ships a native PEP 517 build backend (`uv_build`) that has
been the **default** backend for `uv init --lib` / `--package` since uv
0.8.0 (production-ready since ~0.7.16). For pure-Python packages — no C
extensions, no Cython, no Rust — `uv_build` is 10–35x faster than
hatchling, flit, setuptools, or poetry-core. New library projects get it
automatically; choosing a *different* backend is now the opt-out. To set
it explicitly at `uv init` time:

```bash
uv init --build-backend uv_build mylib
```

Or in an existing project, swap `[build-system]`:

```toml
# pyproject.toml
[build-system]
requires = ["uv_build>=0.11,<0.12"]
build-backend = "uv_build"
```

See the [uv_build backend docs](https://docs.astral.sh/uv/concepts/projects/build-backend/)
and the [introductory write-up](https://pydevtools.com/blog/uv-build-backend/).

**Why.** Two concrete wins, one trade-off:

1. **Build time.** For a single pure-Python wheel, `uv_build` typically completes in 10–100 ms versus 500 ms – 3 s for hatchling / setuptools (which import the full Python build stack first). At repo scale (workspace with 20 members, monorepo CI rebuilds), this compounds into multi-minute savings per pipeline run.
2. **No extra dependency.** `uv_build` is shipped *as part of uv*. `[build-system] requires = ["uv_build"]` resolves to a tiny shim that delegates to the running uv binary. Hatchling/setuptools each pull in their own dependency tree (`pathspec`, `pluggy`, ...) into the build env.

Trade-offs:

1. **Pure-Python only.** No support for C / Rust extensions, no
   custom build hooks, no plugin system. If you need maturin (Rust),
   `setuptools-rust` (C/C++), or a hatch plugin, stay with that
   backend. The uv docs are explicit about this scope.
2. **Namespace / divergent import names need explicit configuration.**
   Implicit namespace packages (a `foo/bar/` directory without
   `foo/__init__.py`) require `[tool.uv.build-backend] namespace =
   true`. As of uv 0.11.17, `uv_build` also supports PEP 794
   `import-names` / `import-namespaces`, covering packages whose import
   name differs from the distribution name (e.g. dist `my-lib`, import
   `mylib`) — a case that previously forced hatchling (see UVP-071).

For most libraries — which are pure Python — `uv_build` is the right
default in 2026.

**How.**

```toml
# pyproject.toml — pure-Python library with uv_build
[project]
name = "mylib"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["httpx"]

[build-system]
requires = ["uv_build>=0.11,<0.12"]
build-backend = "uv_build"

# default layout: src/mylib/ — no extra config needed
```

```bash
# scaffold a new project with uv_build from the start
uv init --build-backend uv_build --lib mylib

# build the wheel (uses uv_build per pyproject.toml)
uv build

# inspect what got built
ls dist/
# mylib-0.1.0-py3-none-any.whl
# mylib-0.1.0.tar.gz
```

For a workspace where every member is pure Python:

```toml
# each member's pyproject.toml
[build-system]
requires = ["uv_build>=0.11,<0.12"]
build-backend = "uv_build"
```

Namespace package opt-in:

```toml
[tool.uv.build-backend]
namespace = true                  # allow src/foo/bar/ without src/foo/__init__.py
```

**When NOT to apply.** Anything that's not a pure-Python wheel:

- **C / C++ / Cython extensions** → stick with `setuptools`, `meson-python`, or `scikit-build-core`.
- **Rust extensions** → `maturin`.
- **Projects relying on hatch plugins** (`hatch-vcs`, `hatch-fancy-pypi-readme`, `hatchling`'s file-include DSL) → stay on hatchling; the plugin ecosystem doesn't port.
- **Projects with custom build hooks** (generating Python from a `.proto` file at build time, embedding a JS bundle) → use a backend with a hooks API.

`uv_build` is the right default for *new* pure-Python projects and
for *existing* projects whose only build-backend usage is "produce a
wheel." It's not a forced migration.

---

## UVP-071 — `uv_build` supports PEP 794 `import-names` for divergent import/distribution names

**What.** Since uv 0.11.17, `uv_build` supports PEP 794 `import-names` /
`import-namespaces`, covering packages where the import name differs from
the distribution name (dist `my-lib`, imported as `mylib`), packages that
expose multiple modules, and some namespace-package shapes that
previously forced hatchling.

**Why.** Before 0.11.17, a package whose distribution and import names
diverged (the classic `Pillow` → `PIL`) couldn't use `uv_build` and had
to stay on setuptools/hatchling. It can migrate now — but failing to
declare `import-names` when the names diverge makes `uv_build` look for a
module named after the distribution, not find it, and emit a broken
wheel.

**How.**

```toml
[tool.uv.build-backend]
module-name = "mylib"                    # single module after normalization
# or, for divergent / multiple names (PEP 794):
import-names = ["mylib", "mylib_extras"]
```

**When NOT to apply.** Pure-Python packages where the import name already
matches the distribution name (the common case) need none of this. C/Rust
extensions and hatch-plugin users stay on their backend regardless (see
UVP-029).

---

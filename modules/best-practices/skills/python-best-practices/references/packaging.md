# PY packaging rules

Detailed entries for `PY-060..PY-066` plus newer
packaging-and-security-adjacent rules (`PY-070`, `PY-072`,
`PY-073`, `PY-075`, `PY-077`, `PY-078`). Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the
[PyPA packaging guide](https://packaging.python.org/),
[PEP 621](https://peps.python.org/pep-0621/) (project metadata),
[PEP 639](https://peps.python.org/pep-0639/) (license expressions),
[PEP 702 — deprecated decorator](https://peps.python.org/pep-0702/),
[PEP 723 — inline script metadata](https://peps.python.org/pep-0723/),
[PEP 740 — provenance attestations](https://peps.python.org/pep-0740/),
[PyPI Trusted Publishers docs](https://docs.pypi.org/trusted-publishers/),
[pip-audit](https://pypi.org/project/pip-audit/),
[scalene](https://github.com/plasma-umass/scalene),
[py-spy](https://github.com/benfred/py-spy),
and [PEP 440](https://peps.python.org/pep-0440/) (versioning).

---

## PY-060 — `license` is an SPDX string (PEP 639); table form deprecated

**What.** Declare your project's license as an SPDX expression
string. The old `{text = "MIT"}` and `{file = "LICENSE"}` table
forms are deprecated by PEP 639 (accepted, rollout deadline
February 2026):

```toml
# RIGHT — PEP 639 SPDX string
[project]
license = "MIT"
license-files = ["LICENSE"]

# Also right — composite SPDX expression
[project]
license = "Apache-2.0 OR MIT"
license-files = ["LICENSE-APACHE", "LICENSE-MIT"]

# WRONG (deprecated)
[project]
license = {text = "MIT"}
license = {file = "LICENSE"}
```

**Why.** Three concrete failures from the old format:

1. **setuptools ≥77 emits deprecation warnings** for the table form. setuptools 80+ may make it an error. Newer build backends (hatchling 1.27+) accept both but prefer the string form.
2. **PyPI rejects uploads with deprecated metadata.** As of the PEP 639 rollout, PyPI's verification flags table-form license and refuses the release. The error message points at the metadata fields, not the pyproject.toml form, so it's confusing to debug.
3. **License scanners (Snyk, FOSSA, Trivy) understand SPDX.** Composite expressions like `"Apache-2.0 OR MIT"` are machine-parseable; `{text = "MIT (with patent grant; see LICENSE)"}` is not. Auditors lose machine readability when you encode license logic in prose.

For composite licenses, SPDX expressions support `AND`, `OR`, and
`WITH`:

```toml
license = "Apache-2.0 WITH LLVM-exception"
license = "(Apache-2.0 OR MIT) AND BSD-3-Clause"
```

**How.**

```toml
# Simple
[project]
license = "MIT"
license-files = ["LICENSE"]

# Multi-file (e.g. dual-licensed)
[project]
license = "Apache-2.0 OR MIT"
license-files = ["LICENSE-APACHE", "LICENSE-MIT"]

# Glob (subset)
[project]
license = "BSD-3-Clause"
license-files = ["LICENSES/*"]
```

If you genuinely have a non-SPDX-listed license (custom EULA, etc.),
SPDX provides `LicenseRef-` for that:

```toml
license = "LicenseRef-MyCompany-Internal"
license-files = ["LICENSE"]
```

**When NOT to apply.** Build backends that don't yet support PEP 639
(some older Poetry versions). Most contemporary backends support
it; check your build-backend's minimum version requirement.

---

## PY-061 — Derive version from git tags; declare `dynamic = ["version"]`

**What.** Don't hand-maintain a version string in both
`pyproject.toml` and `__init__.py` (they will drift). Use a build
backend plugin that derives the version from git tags at build
time, and declare the version as `dynamic`:

```toml
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[project]
name = "my-package"
dynamic = ["version"]      # version comes from VCS

[tool.hatch.version]
source = "vcs"
```

For setuptools-based projects, use `setuptools-scm`:

```toml
[build-system]
requires = ["setuptools>=68", "setuptools-scm>=8"]
build-backend = "setuptools.build_meta"

[project]
name = "my-package"
dynamic = ["version"]

[tool.setuptools_scm]
write_to = "src/mypackage/_version.py"
```

**Why.** Two failure modes from hand-maintained versions:

1. **Drift between sources.** A release cut with `version = "1.2.3"` in `pyproject.toml` and `__version__ = "1.2.4"` in `__init__.py` produces an inconsistent package — `pip show` says one number, `python -c "import mypackage; print(mypackage.__version__)"` says another. Users hit confusing version-mismatch bugs.
2. **Forgotten bump.** Cut a release, push tag `v1.2.3`, forget to update `pyproject.toml`. The release is built as version `1.2.2` (whatever was last in pyproject), confuses your registry, and you can't re-release v1.2.3 because the version is reserved.

VCS-derived versions eliminate both: the tag is the version. Bump
the tag, build, publish. The `__version__` attribute (if needed at
runtime) reads from package metadata:

```python
# src/mypackage/__init__.py
from importlib.metadata import version
__version__ = version("mypackage")
```

**How.** hatch-vcs setup:

```toml
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[project]
name = "my-package"
dynamic = ["version"]

[tool.hatch.version]
source = "vcs"
# Optional: customize the version format
# fallback-version = "0.0.0.dev"

[tool.hatch.build.hooks.vcs]
# Optional: write a version file at build time
version-file = "src/mypackage/_version.py"
```

setuptools-scm setup:

```toml
[build-system]
requires = ["setuptools>=68", "setuptools-scm>=8"]
build-backend = "setuptools.build_meta"

[tool.setuptools_scm]
# Writes the version on build so package can read it at runtime
write_to = "src/mypackage/_version.py"
version_scheme = "post-release"        # or "guess-next-dev", etc.
local_scheme = "no-local-version"      # important for PyPI publishing
```

Tag and release:

```bash
# Update CHANGELOG, commit
git tag v1.2.3
git push --tags

# Build — version is "1.2.3" from the tag
uv build

# Publish (PY-062 — trusted publishing in CI)
```

**When NOT to apply.** Two real cases:

1. **No git repo.** Internal tooling distributed without VCS — hardcode in `pyproject.toml` only (not `__init__.py`).
2. **Calendar versioning.** If you release on a schedule (`2026.05.01`) and want explicit control, hardcoded versions in pyproject.toml are simpler. Even then, don't duplicate the string in `__init__.py`.

---

## PY-062 — Publish via Trusted Publishing (OIDC), not API tokens

**What.** Configure PyPI Trusted Publishing for your GitHub Actions
workflow. The publish step uses
`pypa/gh-action-pypi-publish` with `id-token: write` permission —
no API token needed.

```yaml
# .github/workflows/publish.yml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    environment: pypi              # require manual approval in repo settings
    permissions:
      id-token: write              # MANDATORY for OIDC trusted publishing
      contents: read
    steps:
      - uses: actions/checkout@<sha>     # v5
        with:
          fetch-depth: 0                  # need full history for hatch-vcs
      - uses: astral-sh/setup-uv@<sha>    # v8
      - name: Build
        run: uv build
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@<sha>    # release/v1
        # No `with: password:` — OIDC handles auth
```

Register the trusted publisher at
`https://pypi.org/manage/account/publishing/`:

- Project name: `my-package`
- Owner: your GitHub org/user
- Repository: `my-package`
- Workflow filename: `publish.yml`
- Environment name: `pypi`

**Why.** Three real reasons:

1. **Long-lived API tokens are a persistent credential.** Stored as a `secrets.PYPI_API_TOKEN`, a token can be exfiltrated by a malicious dependency, a compromised CI step, or a leaked log. Once leaked, the attacker has unlimited time to publish malicious releases.
2. **OIDC tokens are ephemeral.** GitHub issues a short-lived (~15-minute) JWT signed by GitHub's keys, scoped to one workflow run. PyPI verifies the signature and the claim (this repo, this workflow, this environment). A leaked OIDC token expires before it can be reused.
3. **Trusted Publishing is PyPI's current recommendation.** It's been the default-recommended path since 2023; PyPI's UI nudges users toward it. API tokens still work but are documented as the legacy path.

The GitHub environment requirement (`environment: pypi`) adds a
manual-approval gate — combined with OIDC, even a compromised
workflow can't publish without the approval step.

**How.** End-to-end shape:

```yaml
# .github/workflows/publish.yml
name: Publish

on:
  release:
    types: [published]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@<sha>
      - run: uv build
      - uses: actions/upload-artifact@<sha>
        with:
          name: dist
          path: dist/

  publish-testpypi:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: testpypi
      url: https://test.pypi.org/p/my-package
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@<sha>
        with: { name: dist, path: dist/ }
      - uses: pypa/gh-action-pypi-publish@<sha>
        with:
          repository-url: https://test.pypi.org/legacy/

  publish-pypi:
    needs: publish-testpypi
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/p/my-package
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@<sha>
        with: { name: dist, path: dist/ }
      - uses: pypa/gh-action-pypi-publish@<sha>
        # No URL = defaults to PyPI
```

Setup: register the publishers at
`https://pypi.org/manage/account/publishing/` and
`https://test.pypi.org/manage/account/publishing/` matching the
environment names.

**PEP 740 attestations come along for free** in
`pypa/gh-action-pypi-publish` v1.11+ when Trusted Publishing is
active — but only if the publish job has `permissions:
attestations: write`. Without that permission, the action falls
back to publishing without attestations and prints a one-line
warning that is easy to miss. See PY-075 for the full
attestation rule and the permission block.

**When NOT to apply.** Two cases:

1. **Private indexes (Artifactory, internal Pulp).** Trusted Publishing is a PyPI/TestPyPI feature; private indexes typically still require API tokens or basic auth.
2. **Publishing from non-GitHub CI** without OIDC support. GitLab supports OIDC for PyPI; CircleCI does too. If your CI doesn't, fall back to short-lived API tokens (rotated frequently, scoped to one project, stored as a CI secret).

---

## PY-063 — Build with `uv build` or `python -m build`; produce sdist + wheel

**What.** Every PyPI release should include both a source
distribution (`.tar.gz`) and at least one wheel (`.whl`).
`uv build` (uv projects) or `python -m build` (tool-agnostic) are
the current standard frontends. Verify with `twine check dist/*`
before publishing.

```bash
# uv projects — uv build produces both
uv build
# → dist/my_package-1.2.3-py3-none-any.whl
# → dist/my_package-1.2.3.tar.gz

# Tool-agnostic frontend (any pyproject.toml backend)
python -m build

# Verify
twine check dist/*
```

**Why.** Two failure modes from getting this wrong:

1. **sdist-only.** Every install requires building from source. Slow (compilation, dependency resolution); requires build toolchain on the user's machine; doesn't work in environments without compilers (Alpine in slim Docker, Lambda layers). Wheels are pre-built — `pip install` becomes a download + unpack, no build step.
2. **Wheel-only.** Users can't inspect the source, can't patch locally, can't build alternate variants (Alpine musl wheels, ARM wheels for unusual platforms). conda-forge, Nix, and Alpine Linux's build systems all consume sdists. Skipping sdist means your package can't be packaged into those ecosystems.

For pure-Python packages, both sdist and wheel are cheap. For
packages with native extensions, wheel + sdist is still the right
shape — publish pre-built wheels for the platforms you support,
and the sdist as a fallback.

`python setup.py bdist_wheel` is **removed** in Python 3.12+ and
should never be used in new code. Use `python -m build` or
`uv build`.

**How.**

```bash
# Clean previous builds
rm -rf dist/

# Build
uv build               # or: python -m build

# Result
ls dist/
# my_package-1.2.3-py3-none-any.whl
# my_package-1.2.3.tar.gz

# Verify metadata
twine check dist/*
# Checking dist/my_package-1.2.3-py3-none-any.whl: PASSED
# Checking dist/my_package-1.2.3.tar.gz: PASSED
```

Common `twine check` failures:

- Missing `Description-Content-Type` — your `readme` needs `content-type`:
  ```toml
  readme = {file = "README.md", content-type = "text/markdown"}
  ```
- Deprecated license format (PY-060).
- Long description fails to render as Markdown (PyPI parses it server-side).

**When NOT to apply.** Single-file scripts and internal tooling
that don't ship anywhere — no need to build at all. The rule
applies to packages destined for PyPI or an internal index.

---

## PY-064 — Verify on TestPyPI before publishing to PyPI

**What.** Every new package — first release, or any release where
you suspect metadata might be wrong — uploads to TestPyPI first to
catch issues that only surface server-side.

```yaml
# .github/workflows/publish.yml — TestPyPI step
publish-testpypi:
  steps:
    - uses: pypa/gh-action-pypi-publish@<sha>
      with:
        repository-url: https://test.pypi.org/legacy/

# Then manually verify the rendered page:
# https://test.pypi.org/project/my-package/<VERSION>/
```

**Why.** PyPI is one-shot: you cannot overwrite a released version.
If your wheel uploads with a broken README that PyPI fails to
render, you can yank (hide) the release but can't *replace* it with
the same version number. You have to bump to v1.2.4, re-release,
and live with v1.2.3 forever in your registry history.

TestPyPI rendering catches most of these:

- README markdown that doesn't render server-side (PyPI uses a stricter renderer than GitHub).
- Missing `Description-Content-Type` causing the README to display as raw markdown.
- Missing `Project-URL` entries — the sidebar is blank, "looks abandoned."
- Classifier typos — pages list "Unknown" instead of "Production/Stable."
- License-file packaging issues (LICENSE not bundled in sdist).
- Wheel filename or platform-tag mistakes.

**How.**

```bash
# Build
rm -rf dist/
uv build

# Upload to TestPyPI
uv publish --publish-url https://test.pypi.org/legacy/ dist/*
# or:
twine upload --repository testpypi dist/*

# Manually verify
open https://test.pypi.org/project/my-package/

# Install from TestPyPI to confirm it imports cleanly
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            my-package

# When happy, publish to real PyPI
uv publish dist/*
# or:
twine upload dist/*
```

For new projects, also register the package name on TestPyPI
first — names are reserved on a first-come-first-served basis on
each index, so confirm yours is available before announcing it.

**When NOT to apply.** Subsequent patch releases of a long-stable
package where you're only changing code, not metadata, and the
release pipeline is well-tested. The TestPyPI step is most
valuable for new packages and metadata changes. Even then, the
cost is low (one extra CI job); leaving it in the pipeline
permanently is fine.

---

## PY-065 — Dev deps in `[project.optional-dependencies]`, never `[project.dependencies]`

**What.** `[project.dependencies]` is what end users get when they
`pip install my-package`. Dev / test / docs tools (pytest, mypy,
ruff, mkdocs) go in `[project.optional-dependencies]` or, for uv
projects, `[dependency-groups]` (see UVP-001 in `uv-best-practices`).
Never in `[project.dependencies]`.

```toml
# RIGHT
[project]
dependencies = [
  "httpx>=0.27",          # runtime — installed for users
  "pydantic>=2",
]

[project.optional-dependencies]
dev = ["pytest>=8", "mypy>=1.10", "ruff"]
docs = ["mkdocs", "mkdocs-material"]
test = ["pytest-cov", "hypothesis"]

# WRONG
[project]
dependencies = [
  "httpx>=0.27",
  "pytest>=8",            # gets installed for every user!
  "mypy>=1.10",
]
```

**Why.** Two failure modes:

1. **Dependency tree explosion.** Your library is supposed to be lightweight. Putting pytest in `[project.dependencies]` means every user who `pip install my-package` also installs pytest, pluggy, iniconfig, py, and pytest's transitive deps — adding megabytes and dozens of packages they didn't ask for. In large dependency trees this causes version conflicts.
2. **Confusing "what does this library need?"** A user reading your library's dependencies should see runtime deps. If they see pytest, they might assume you use it at runtime (data-fixture loading? test-mode behavior?). The mistake leaks into how downstream consumers reason about your package.

For uv projects, prefer `[dependency-groups]` over
`[project.optional-dependencies]` (see UVP-001 in `uv-best-practices`):
dependency groups are PEP 735, locally scoped, and don't ship as PyPI
"extras."

**How.**

```toml
# Pure pyproject (no uv) — old PEP 621 extras
[project]
dependencies = ["httpx>=0.27"]

[project.optional-dependencies]
dev = ["pytest>=8", "mypy>=1.10", "ruff"]
docs = ["mkdocs", "mkdocs-material"]
test = ["pytest-cov", "hypothesis"]

# Users install dev tools via extras:
# pip install "my-package[dev]"
# pip install "my-package[dev,docs]"
```

```toml
# uv projects — prefer dependency-groups for dev concerns
[project]
dependencies = ["httpx>=0.27"]

# Extras still belong in [project.optional-dependencies] when you
# want consumers to install them via `pip install "my-package[name]"`:
[project.optional-dependencies]
async = ["aiohttp"]            # extra runtime feature

# Dev concerns go in dependency-groups (see UVP-001):
[dependency-groups]
dev = ["pytest>=8", "mypy>=1.10", "ruff"]
docs = ["mkdocs", "mkdocs-material"]
```

The distinction:

- **`optional-dependencies`** is for runtime *extras* consumers might install (`my-package[async]`).
- **`dependency-groups`** is for *your* dev workflow — never shipped to PyPI consumers.

**When NOT to apply.** Pre-PEP-735 tooling that doesn't understand
`[dependency-groups]` — but in 2026 nearly all current tooling
does (pip ≥25.1, uv, hatch, PDM). The rule applies universally.

---

## PY-066 — `warnings.warn(..., DeprecationWarning, stacklevel=2)` for public API deprecations

**What.** When deprecating a public API, emit a `DeprecationWarning`
at least one minor version before removal. Pass `stacklevel=2` so
the warning points at the *caller's* line, not your library's
internal `warnings.warn` line.

On Python 3.13+ (or with `typing_extensions`), see PY-070 — the
`@warnings.deprecated` decorator (PEP 702) is the modern shape
and gives static type checkers + IDEs visibility into the
deprecation at edit time. Use this `warnings.warn(...,
stacklevel=2)` pattern as the fallback for pre-3.13 environments
or for one-off conditional deprecations (e.g. deprecating only a
specific argument value).

```python
import warnings

def old_function(x):
    warnings.warn(
        "old_function() is deprecated and will be removed in v3.0. "
        "Use new_function() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return new_function(x)
```

**Why.** Two failure modes:

1. **No deprecation warning before removal.** Users who depended on the API discover the breakage in v3.0 when their code crashes. They have no warning during the v2.x cycle that they should migrate. Always: deprecate in vN.Y, remove in v(N+1).0.
2. **`stacklevel=1` (the default) points at the wrong code.** The warning says "deprecated at `mylib/old_module.py:42`" — useless to the user, who needs to know which of *their* lines call this. `stacklevel=2` points at the caller; `stacklevel=3` at the caller's caller (use when wrapping the warn call in a helper).

Concretely: `stacklevel=1` produces output like:

```
/site-packages/mylib/legacy.py:42: DeprecationWarning: old_function() is deprecated
  warnings.warn("old_function() ...", DeprecationWarning)
```

— the user has to grep their own code for "where do I call
`old_function`?" `stacklevel=2`:

```
/myapp/handlers/users.py:123: DeprecationWarning: old_function() is deprecated
  result = mylib.old_function(user_id)
```

— directly actionable.

**How.**

```python
import warnings
from typing import Any
from functools import wraps

# Function-level deprecation
def old_api(x: int) -> int:
    warnings.warn(
        "old_api() is deprecated since v2.5 and will be removed in v3.0. "
        "Use new_api(x, mode='compat') instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return new_api(x, mode="compat")

# Class-level (use __init_subclass__ or a metaclass for inherited deprecation)
class OldClient:
    def __init__(self, *args, **kwargs):
        warnings.warn(
            "OldClient is deprecated. Use Client instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)

# Argument-level
def fetch(url: str, timeout: int | None = None, retry: int | None = None) -> bytes:
    if retry is not None:
        warnings.warn(
            "fetch(retry=...) is deprecated; pass retry_policy=RetryPolicy(...) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    ...

# Decorator pattern for clean reuse
def deprecated(reason: str, *, removal: str | None = None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            msg = f"{fn.__name__}() is deprecated. {reason}"
            if removal:
                msg += f" Removed in {removal}."
            warnings.warn(msg, DeprecationWarning, stacklevel=2)
            return fn(*args, **kwargs)
        return wrapper
    return decorator

@deprecated("Use new_api() instead.", removal="v3.0")
def old_api(x):
    ...
```

For libraries that document deprecation policy, write the version
schedule into the warning text and the CHANGELOG:

- v2.5 — emit DeprecationWarning (still works)
- v2.6 — emit louder warning, possibly elevate to a custom subclass
- v3.0 — remove

Test the warnings in your test suite with `pytest.warns`:

```python
import pytest
import mylib

def test_old_api_deprecated():
    with pytest.warns(DeprecationWarning, match="v3.0"):
        mylib.old_api(42)
```

**When NOT to apply.** Two cases:

1. **Pre-1.0 software.** API breakage is expected; the version number itself signals "no compatibility guarantees yet." Skip the deprecation cycle; just break and note in the CHANGELOG.
2. **Internal helpers.** `_private_function` is not part of the public API; you can change or remove it without a deprecation warning. The rule applies to documented public APIs.

---

## PY-070 — `@warnings.deprecated` (PEP 702) for type-checker-visible deprecations

**What.** On Python 3.13+ (or `typing_extensions ≥ 4.5`), decorate
deprecated callables and classes with
[`@warnings.deprecated`](https://peps.python.org/pep-0702/). This
both emits the `DeprecationWarning` at runtime and tells type
checkers / IDEs to flag *call sites* with an inline deprecation
diagnostic — before the user ever runs the code.

```python
import warnings

@warnings.deprecated("Use new_api() instead. Removed in v3.0.")
def old_api(x: int) -> int:
    return new_api(x, mode="compat")

@warnings.deprecated("OldClient is deprecated; use Client.")
class OldClient(Client):
    ...
```

A call to `old_api(5)` now produces:

- A `DeprecationWarning` at runtime (same as PY-066).
- An inline squiggle / diagnostic in pyright, mypy, and any IDE
  using either — *before* the code runs.

**Why.** The runtime-warning-only approach (PY-066) has a real
gap: developers only see the deprecation when the code actually
runs and the warning filter happens to be permissive. In a test
suite that filters `DeprecationWarning` by default (which is the
Python default), the warning is silenced until production —
exactly when you don't want to discover it.

`@warnings.deprecated` plugs that gap:

1. **Type checkers see it.** pyright (≥ 1.1.350) and mypy (≥ 1.11) implement PEP 702 and flag every call site with a `deprecated` diagnostic. Errors-as-CI-gate stacks catch the deprecation before merge.
2. **IDEs see it.** VS Code / PyCharm render the call with a strikethrough or warning underline. Developers see deprecations during typing, not at runtime.
3. **`stacklevel` is automatic.** The decorator computes the correct stack level internally; no risk of forgetting it.

The runtime behavior is identical to `warnings.warn(...,
DeprecationWarning, stacklevel=...)` — same warning class, same
filters, same `pytest.warns(DeprecationWarning)` semantics.

**How.**

```python
# 3.13+ — stdlib
import warnings

@warnings.deprecated("old_api() is deprecated; use new_api(). Removed in v3.0.")
def old_api(x: int) -> int:
    return new_api(x, mode="compat")

# pre-3.13 — typing_extensions backport
from typing_extensions import deprecated

@deprecated("OldClient is deprecated; use Client.")
class OldClient(Client):
    ...

# Decorator + the function still works at runtime
result = old_api(5)            # runtime: DeprecationWarning fires
                                # static:  pyright/mypy flag the call
```

Side-by-side with the PY-066 form:

```python
# PY-066 — works on every Python; runtime-only signal
def old_api(x: int) -> int:
    warnings.warn(
        "old_api() is deprecated; use new_api().",
        DeprecationWarning,
        stacklevel=2,
    )
    return new_api(x, mode="compat")

# PY-070 — runtime + static; needs 3.13 or typing_extensions
@warnings.deprecated("old_api() is deprecated; use new_api().")
def old_api(x: int) -> int:
    return new_api(x, mode="compat")
```

The decorator form is additive — `stacklevel` is handled
internally, so you don't need to drop the PY-066 knowledge; you
just don't need to *apply* it manually for the common case.

For conditional or argument-level deprecations (deprecating
`fetch(retry=...)` but not `fetch(retry_policy=...)`), the
decorator can't help — fall back to `warnings.warn(...,
stacklevel=2)` inside the function body (PY-066).

**When NOT to apply.** Three cases:

1. **Libraries supporting Python < 3.13 without `typing_extensions`.** The decorator doesn't exist; use PY-066.
2. **Conditional deprecations.** Deprecating one argument value, one combination of kwargs, or behavior triggered by environment — `@warnings.deprecated` decorates the *callable*, not branches inside it. Use PY-066 inline.
3. **Tools-don't-understand-it cases.** If your team's static checker doesn't yet implement PEP 702 (very old pyright/mypy), the decorator works at runtime but you lose the static signal. Either upgrade or live with the runtime-only behavior (which is still equivalent to PY-066).

---

## PY-072 — PEP 723 inline script metadata for standalone scripts

**What.** For single-file scripts that have dependencies, declare
those dependencies inline using
[PEP 723](https://peps.python.org/pep-0723/) script metadata.
Modern runners (`uv run`, `pipx run`) consume the block and create
an ephemeral environment automatically — no `requirements.txt`, no
separate venv, no `pip install` step:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.27",
#   "rich",
# ]
# ///

import httpx
from rich.console import Console

console = Console()
resp = httpx.get("https://httpbin.org/json")
console.print_json(data=resp.json())
```

Run it:

```bash
uv run scrape.py            # uv reads the block, makes a venv, runs
chmod +x scrape.py && ./scrape.py   # via shebang
pipx run scrape.py          # pipx also supports the block
```

**Why.** The pre-PEP-723 alternatives are noticeably worse for
small tools:

1. **Bare `pip install` + manual venv.** Every new clone of the script needs the user to `pip install httpx rich` somewhere — locally, in a venv, in user site-packages. No isolation; pollutes whatever environment is active.
2. **A `requirements.txt` next to a `.py` file.** Two files, no manifest tying them together, and the user still has to know to `pip install -r` before running.
3. **Wrapping in a package.** Setting up `pyproject.toml`, src layout, build backend — wildly overkill for a 40-line scraping script.

PEP 723 collapses the script + its requirements into one
self-contained file. The first run pays a one-time resolve cost;
subsequent runs are cached. The script can be moved between
machines, pasted into a Gist, or attached to a ticket and it still
runs deterministically wherever uv is installed.

The metadata format is parseable by any tool that follows the PEP:
the block starts with `# /// script`, ends with `# ///`, and the
content between is TOML. `uv init --script foo.py` scaffolds a new
script with the block populated.

**Boundary.** This rule covers the **metadata format** (when to
use it, what shape it takes). The mechanics of running scripts
with uv — `uv run --script`, lockfile-for-scripts (`uv lock
--script`), environment caching — live in
[`uv-best-practices`](../../uv-best-practices/). When advising
"use PEP 723," point at this rule; for "how does `uv run`
actually resolve this," point at uv-best-practices.

**How.**

```bash
# Scaffold a new script
uv init --script extract.py

# Add a dependency to an existing script
uv add --script extract.py httpx
```

```python
# extract.py
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.27",
#   "click>=8",
# ]
# ///

import click, httpx

@click.command()
@click.argument("url")
def main(url: str) -> None:
    resp = httpx.get(url)
    click.echo(resp.text)

if __name__ == "__main__":
    main()
```

The PEP 723 fields mirror a subset of `[project]` from
`pyproject.toml`: `requires-python`, `dependencies`. Pinned
versions are encouraged for reproducibility; ranges (`httpx>=0.27`)
are fine when the script is robust to minor-version drift.

**When NOT to apply.** Three cases:

1. **Anything that's not a single file.** If your "script" has imported `helpers.py` siblings, it's a package; use a real `pyproject.toml`.
2. **Scripts that run inside an already-curated environment** (CI workers, Docker containers with pre-installed deps). The block adds no value — the environment is fixed elsewhere.
3. **Libraries.** A library is published to PyPI; its dependencies belong in `pyproject.toml`. PEP 723 is for executable scripts, not library code.

---

## PY-073 — Use `datetime.now(UTC)`; never `datetime.utcnow()`

**What.** Always construct timezone-aware datetimes. `datetime.utcnow()`
and `datetime.utcfromtimestamp()` are deprecated as of Python 3.12
(active `DeprecationWarning` on each call) and produce **naive**
datetimes — which silently misbehave at system boundaries.

```python
# RIGHT — 3.11+
from datetime import datetime, UTC
now = datetime.now(UTC)                          # tz-aware

# RIGHT — 3.10 fallback
from datetime import datetime, timezone
now = datetime.now(timezone.utc)                 # tz-aware

# WRONG — deprecated, produces naive datetime
now = datetime.utcnow()                          # DeprecationWarning in 3.12+

# WRONG — also naive
now = datetime.now()                             # local-time, no tz info
```

For Unix timestamps:

```python
# RIGHT
datetime.fromtimestamp(ts, tz=UTC)

# WRONG — deprecated, naive
datetime.utcfromtimestamp(ts)
```

**Why.** The silent danger of naive datetimes is that they *look*
correct everywhere they're constructed but blow up at boundaries:

1. **Comparison with aware datetimes raises `TypeError`.** `naive < aware` errors out with `can't compare offset-naive and offset-aware datetimes`. The error often surfaces months after the naive value was introduced — once the data hits a comparison with a value loaded from a tz-aware source (Postgres `timestamptz`, an ISO 8601 API response).
2. **`datetime.utcnow()` is misleadingly named.** It returns the current UTC time, but the resulting object has *no `tzinfo`* — it's a naive datetime that happens to represent a UTC moment. Code that does `naive_utcnow.timestamp()` then assumes local time and silently shifts the value by your local UTC offset. The result is wrong by hours, and there's no warning.
3. **Database round-trips lose information.** A naive datetime written to a `timestamptz` column gets interpreted as local time by some drivers and as UTC by others. Read it back and it's shifted; nobody can tell where the shift came from. Tz-aware datetimes are unambiguous in every direction.

The official fix is documented at length by Miguel Grinberg
("[It's time for a change: datetime.utcnow() is now deprecated](https://blog.miguelgrinberg.com/post/it-s-time-for-a-change-datetime-utcnow-is-now-deprecated)")
and Simon Willison's [TIL on the same topic](https://til.simonwillison.net/python/utcnow).

**How.**

```python
from datetime import datetime, UTC, timezone

# Python 3.11+ — UTC sentinel exists in the datetime module
def now_utc() -> datetime:
    return datetime.now(UTC)

# 3.10 — use timezone.utc
def now_utc_py310() -> datetime:
    return datetime.now(timezone.utc)

# Parsing an ISO string from an API
from datetime import datetime
dt = datetime.fromisoformat("2026-05-26T10:00:00+00:00")   # tz-aware
assert dt.tzinfo is not None

# Storing in Postgres via psycopg / SQLAlchemy
# - column type: TIMESTAMPTZ
# - value:       datetime.now(UTC)         (tz-aware; unambiguous)
```

For sites that already have naive datetimes flowing through them
(legacy databases, old API responses), wrap conversions at the
boundary:

```python
def assume_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
```

Pair with the ruff `DTZ` family (see PY-021's "consider but not
default" list) to detect new naive constructions in CI. `DTZ` is
opt-in because it's noisy on internal-only scripts; for any project
that exchanges timestamps with a database or an external API,
enable it.

**When NOT to apply.** Two narrow cases:

1. **Wall-clock-local display.** Code that intentionally formats a datetime in the user's local time for display (e.g. "scheduled at 3:00 PM local") still needs to *compute* in tz-aware UTC, then `astimezone(local_tz)` for rendering. Don't reach for `datetime.now()` (naive local) as a shortcut — it strips the tz info and you can't recover it.
2. **A single throwaway script that never persists or transmits the datetime.** `datetime.now()` to print "started at ..." in a 10-line script is fine. The rule kicks in the moment a datetime crosses a boundary.

---

## PY-075 — Enable PEP 740 build provenance attestations

**What.** When publishing via Trusted Publishing (PY-062), PyPI
also accepts **PEP 740 build provenance attestations** — a signed
record that ties this artifact back to the exact GitHub Actions
workflow + commit SHA that produced it. As of
`pypa/gh-action-pypi-publish` v1.11+ this is **automatic** when
Trusted Publishing is active, *provided* the publish job has
`permissions: attestations: write`. Without that permission, the
action falls back to publishing without attestations and prints a
warning that is easy to miss in CI logs.

```yaml
publish-pypi:
  runs-on: ubuntu-latest
  environment:
    name: pypi
    url: https://pypi.org/p/my-package
  permissions:
    id-token: write              # PY-062 — Trusted Publishing
    attestations: write          # PY-075 — PEP 740 attestations
    contents: read
  steps:
    - uses: actions/download-artifact@<sha>
      with: { name: dist, path: dist/ }
    - uses: pypa/gh-action-pypi-publish@release/v1   # v1.11+
      # No extra `with:` block — attestations are automatic when
      # `id-token: write` AND `attestations: write` are both granted.
```

**Why.** Without attestations, anyone with publish rights — or
anyone who compromises an API token, a CI runner, or a maintainer
account — can publish a tampered wheel that looks identical to a
legitimate one. Trusted Publishing solves the auth problem; PEP 740
solves the **provenance** problem.

Concretely, a PEP 740 attestation records:

- The workflow file path (`.github/workflows/publish.yml`).
- The repository (`org/repo`).
- The commit SHA the build was produced from.
- The runner identity (GitHub-hosted vs. self-hosted).

Consumers can verify the attestation at install time with `pip
install --require-hashes ...` plus `pip-audit` or `sigstore-python`
checks, and downstream projects (Linux distros, conda-forge,
internal mirrors) can validate the chain before accepting the
artifact. See [the PyPI announcement](https://blog.pypi.org/posts/2024-11-14-pypi-now-supports-digital-attestations/)
and [PEP 740](https://peps.python.org/pep-0740/) for the full
spec.

The silent failure mode is the permissions slip: if
`attestations: write` is missing, `gh-action-pypi-publish` still
succeeds (it falls back to non-attested upload). You get a release
that looks fine until a consumer asks "where's the attestation?"
and you have to re-cut from the same SHA with the permission
added — which works, but is annoying.

**How.**

```yaml
# .github/workflows/publish.yml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/p/my-package
    permissions:
      id-token: write              # OIDC for Trusted Publishing
      attestations: write          # PEP 740
      contents: read
    steps:
      - uses: actions/checkout@<sha>
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@<sha>
      - run: uv build
      - uses: pypa/gh-action-pypi-publish@release/v1
```

Verify after publish:

```bash
# Show the attestation PyPI accepted
pip install pypi-attestations
python -m pypi_attestations inspect my-package

# Or via PyPI's web UI:
# https://pypi.org/project/my-package/<version>/  → "Provenance" section
```

This rule **extends** PY-062 rather than replacing it: Trusted
Publishing is still the auth mechanism; PEP 740 is the additional
provenance layer that rides on the same OIDC token.

**When NOT to apply.** Two cases:

1. **Private indexes that don't speak PEP 740.** Same boundary as PY-062 — Artifactory / internal Pulp don't yet ingest the attestation. The flag is harmless (action silently skips), so leaving it enabled is fine; just don't expect verification on the private side.
2. **Non-GitHub CI without Sigstore signing.** PEP 740 attestations are produced via Sigstore; the GitHub Action handles this transparently. GitLab + Sigstore is possible but more setup; CircleCI etc. have varied support. If your CI doesn't have a clean Sigstore path, you can ship without attestations — but you give up the provenance signal until you can.

---

## PY-077 — Audit dependencies for known CVEs in CI

**What.** Run [`pip-audit`](https://pypi.org/project/pip-audit/)
(PyPA, OSV-backed) — or `uv audit` for uv projects — as a
**dedicated CI step**, not just locally. Don't gate releases on it
silently; fail the build when an unaddressed advisory hits a
direct or transitive dependency.

```yaml
# .github/workflows/ci.yml — additional job
audit:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@<sha>
    - uses: astral-sh/setup-uv@<sha>
    - run: uv sync --frozen
    - run: uv run pip-audit --strict
```

For uv projects, the native command:

```bash
uv audit
```

**Why.** Three concrete failure modes when this isn't a CI step:

1. **Local-only audits aren't audits.** A developer who runs `pip-audit` manually catches advisories the day they look. Between checks, new CVEs land against pinned versions and nobody knows. CI runs every PR and main-branch push, so the gap shrinks from "weeks" to "minutes."
2. **Transitive vulnerabilities are invisible.** Your `pyproject.toml` lists 12 direct dependencies; your lockfile resolves to 87 packages. Most CVEs hit transitives. `pip-audit` walks the full resolved tree (from the lockfile or installed env) and surfaces every match — manual `pip list` + Google won't.
3. **No coverage gap with Dependabot / Renovate.** Those tools open PRs for *version updates*; they don't have a notion of "this current pin has an advisory I should know about." `pip-audit` complements them: Dependabot keeps versions current, `pip-audit` flags anything dangerous in the meantime.

`uv audit` is the uv-native equivalent. It uses the same OSV
database under the hood (via `uv`'s own resolver state) and runs
faster than re-resolving with `pip-audit`. Functionally equivalent
for the purpose of this rule; pick whichever fits your stack.

**Handling unfixable advisories.** Sometimes a CVE is real but
there's no fix yet (the upstream maintainer hasn't released a
patch). The right response is not to globally `--ignore-vuln` —
that defeats the rule. Instead:

1. Pin the affected dependency to a *specific* version that you've reviewed.
2. Add an inline comment in `pyproject.toml` explaining the CVE ID, the date, and the tracking issue you opened upstream.
3. Use the audit tool's per-vulnerability ignore — `pip-audit --ignore-vuln <ID>` — scoped to that one CVE, not blanket-disabling the check.
4. Re-evaluate on a calendar reminder; remove the ignore as soon as a fix lands.

```toml
# pyproject.toml
[project]
dependencies = [
  "vulnerable-pkg==1.4.3",        # CVE-2026-12345 has no fix; tracking upstream#789
]
```

```bash
pip-audit --ignore-vuln CVE-2026-12345 --strict
```

**How.**

```yaml
# .github/workflows/ci.yml
name: CI

on: [push, pull_request]

jobs:
  test:
    # ... your existing test job

  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>
      - uses: astral-sh/setup-uv@<sha>
      - name: Sync deps (locked)
        run: uv sync --frozen
      - name: Audit
        run: |
          uv run pip-audit --strict \
            --ignore-vuln CVE-2026-12345    # documented in pyproject.toml
```

Or, with uv's native audit:

```yaml
      - run: uv audit
```

For local dev, the same command runs against the dev tree:

```bash
uv run pip-audit
# or:
uv audit
```

**When NOT to apply.** Two narrow cases:

1. **Throwaway scripts with no production exposure.** A one-off script you'll delete next week doesn't need a CI audit. The rule applies to libraries published to PyPI and applications deployed to environments where supply-chain risk matters.
2. **Projects whose lockfile is intentionally stale** (vendoring an old version for reproducibility; security is owned by a sibling system). Document the boundary; don't silently skip.

---

## PY-078 — Profile with `scalene` or `py-spy` before reaching for C / mypyc / Rust

**What.** When a pure-Python workload is too slow, **measure
first**. Reach for [`scalene`](https://github.com/plasma-umass/scalene)
for line-level local profiling (CPU + memory + native-time
attribution) and [`py-spy`](https://github.com/benfred/py-spy) for
low-overhead sampling against running production processes. Only
*after* the profile points at a specific hot path should you
consider `mypyc`, Cython, or a Rust extension.

```bash
# Local — line-level cost breakdown, CPU + memory
uvx scalene src/myapp/cli.py

# Local / production — attach to a running process by PID
sudo uvx py-spy top --pid 12345
sudo uvx py-spy record --pid 12345 -o profile.svg --duration 30
```

**Why.** Two failure modes from skipping the profile step:

1. **You optimize the wrong thing.** A developer "knows" the bottleneck is `parse_record()` because it's called in a loop and feels heavy. After two days porting it to Cython, total runtime drops by 2% — because the actual bottleneck was a synchronous `requests.get` at startup that nobody noticed. Profilers consistently catch this; intuition consistently doesn't.
2. **You take on permanent maintenance cost for marginal wins.** A Rust extension is real ongoing complexity: cross-platform wheels, ABI compatibility, build-time toolchain. If the profile shows the hot path is genuinely CPU-bound pure Python, that cost is paid for a real reason. If the profile shows the hot path is I/O-bound or already running in a C extension under the hood (numpy, pandas), the native extension would buy nothing.

What each profiler is for:

- **scalene** — line-by-line Python *and* native-time attribution, plus memory profiling. The native-time column is the differentiator: it tells you which lines are spent in pure Python vs. in C extensions, so you can tell whether the slow part is even something you *could* speed up by rewriting Python.
- **py-spy** — sampling profiler that attaches to a running process via `ptrace`/equivalent. ~1-2% overhead. Useful for "the prod service is slow right now, what is it doing?" — no instrumentation, no restart, no code changes.

For pure-Python hot paths that the profile genuinely points at,
[`mypyc`](https://mypyc.readthedocs.io/) is the lowest-effort
step up: it compiles type-annotated Python to a C extension, with
no source changes required if your annotations are accurate. Cython
and Rust (via PyO3) are heavier options reserved for the cases
where mypyc can't represent the code (heavy use of dynamic
features, numpy interop where you want SIMD intrinsics).

**Caveat — py-spy and Python 3.12+.** py-spy has had a handful of
reliability and accuracy regressions on 3.12+ tracked in its issue
list — symbol-table changes upstream invalidated some assumptions
the profiler made. Check the
[py-spy issue tracker](https://github.com/benfred/py-spy/issues)
before depending on it for a critical investigation on the
newest Python.

**How.**

```bash
# Quick CPU+memory profile of a script
uvx scalene path/to/script.py

# Profile a specific function with reduced output
uvx scalene --only-functions hot_module.expensive_call \
            --cpu-percent-threshold 1 \
            src/myapp/main.py

# Attach to a running process — sample for 30s, write a flamegraph
sudo uvx py-spy record --pid $(pgrep -f myapp) -o flamegraph.svg -d 30

# Live top-style view of a running process
sudo uvx py-spy top --pid $(pgrep -f myapp)
```

Workflow:

1. Reproduce the slow path with a representative workload.
2. Run `scalene` (locally) or `py-spy record` (against a representative process).
3. Read the top entries by inclusive CPU time. Cross-reference with native-time column (scalene): if the time is in `numpy.sum`, you're not going to speed that up by rewriting `numpy`.
4. *Then* pick the optimization. Often it's "stop calling this in a loop," "cache the result," or "move it to a `ProcessPoolExecutor`" (PY-040). Native rewrites are the last resort.

**When NOT to apply.** Three cases:

1. **The workload is provably I/O-bound.** Profile shows >80% time in `select`/`epoll`/socket reads. No amount of mypyc speeds that up; address with async (PY-040) or batching.
2. **There's no actual performance complaint.** Don't profile for hypothetical wins; profile when something is observably too slow.
3. **You're optimizing a hot path that's already in a C extension.** numpy, pandas, lxml — the Python wrapper around them is typically microseconds. Rewriting that wrapper buys nothing.

## PY-089 — For uv-managed pure-Python projects, prefer the `uv_build` backend

**What.** When a project is managed with uv, Astral's native `uv_build`
backend is a zero-config, fast `[build-system]` choice for pure-Python
packages. It is the default backend for `uv init --lib` / `--package`
since uv 0.8.0. See [UVP-029](../../uv-best-practices/references/packaging.md)
for the uv-side detail and PY-004 for the full backend decision table.

**Why.** For a pure-Python package already in the uv ecosystem,
`uv_build` is simpler than wiring up hatchling and noticeably faster (no
separate build-stack import). It's complementary to PY-004, which keeps
hatchling as the general default — `uv_build` is the better pick
specifically when uv already manages the project.

**How.**

```toml
[build-system]
requires = ["uv_build>=0.11,<0.12"]
build-backend = "uv_build"
```

**When NOT to apply.** Anything with C/Rust extensions, custom build
hooks, or hatch plugins — stay on hatchling / maturin / scikit-build-core
(PY-004). Non-uv workflows where you don't want a uv dependency in the
build chain. `uv_build` is pure-Python only.

---

## PY-090 — Pin dependency hashes and verify them in CI

**What.** Pin cryptographic hashes for your dependencies — `uv lock`
records them automatically; pip needs `--generate-hashes` — and verify
them at install time (`uv sync --frozen`, or pip `--require-hashes`) in
CI and production builds.

**Why.** PyPI supply-chain attacks (typosquatting, dependency confusion,
compromised maintainer accounts) have risen. Hash verification ensures
the artifact you install is bit-for-bit the one you locked, so a tampered
or substituted package on the index fails the install instead of shipping
silently. This pairs with PY-077 (CVE scanning): hashes stop
*substitution*, pip-audit/`uv audit` catch *known-vulnerable* pinned
versions.

**How.**

```bash
# uv: the lockfile carries hashes; verify on install
uv sync --frozen                 # CI / production

# pip alternative
pip install --require-hashes -r requirements.txt   # generated with --generate-hashes
```

Commit the lockfile; use the frozen/require-hashes form in CI, not just
locally.

**When NOT to apply.** Throwaway scripts and local experiments don't need
it. For any deployed service or published artifact, pin and verify.

---

# PY project-layout rules

Detailed entries for `PY-002..PY-009`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the [PyPA packaging guide](https://packaging.python.org/),
[PEP 517](https://peps.python.org/pep-0517/) /
[PEP 518](https://peps.python.org/pep-0518/) /
[PEP 621](https://peps.python.org/pep-0621/) (packaging), and
[PEP 639](https://peps.python.org/pep-0639/) (license expressions).

---

## PY-002 — `pyproject.toml` is the single source of truth

**What.** All project metadata and tool config lives in
`pyproject.toml`. No parallel `setup.py`, `setup.cfg`, or
`MANIFEST.in` for metadata. The `[project]` table (PEP 621) covers
distribution metadata; `[tool.<name>]` tables cover tool config.

**Why.** Split metadata means drift. The most common failure modes:

1. **Version skew.** A project with `version = "1.2.3"` in `pyproject.toml` and `version = "1.2.4"` in `setup.py` produces inconsistent metadata; whichever file the build backend reads first wins, but readers (humans, search results, IDE plugins) may consult the other.
2. **Classifier rot in `setup.cfg`.** Old `setup.cfg` files become invisible — nobody edits them when adding Python versions. PyPI then shows stale classifiers.
3. **Two readme files.** `setup.py: long_description=open("README.rst").read()` plus `pyproject.toml: readme = "README.md"` — only one ships, the other is broken.
4. **`setup.py` is executed at install time** — it's arbitrary Python code with side effects. PEP 517 deprecates this; modern installers (pip ≥21.3, uv) prefer pure-metadata builds.

There is **one** remaining historical reason for a `setup.py` —
editable installs on very old pip versions — and PEP 660 eliminated
that case. There's no reason to keep one in 2025+.

**How.**

```toml
# pyproject.toml — complete shape for a published package
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "my-package"
version = "1.0.0"
description = "Brief one-line summary"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"                       # PEP 639 SPDX string (PY-060)
authors = [{name = "Alice", email = "alice@example.com"}]
classifiers = [
  "Programming Language :: Python :: 3",
  "Operating System :: OS Independent",
]
dependencies = ["httpx>=0.27"]

[project.optional-dependencies]
dev = ["pytest", "mypy", "ruff"]

[project.urls]
Repository = "https://github.com/alice/my-package"

# Tool config — same file
[tool.ruff]
line-length = 88
target-version = "py311"

[tool.mypy]
strict = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--strict-markers"
```

Delete: `setup.py`, `setup.cfg`, `MANIFEST.in` (unless you have a
real reason to specify file inclusion outside what your build backend
supports).

**When NOT to apply.** Legacy repos still on old setuptools (<61).
Migrate when you have any reason to touch packaging config — don't
maintain two parallel sources for new features.

---

## PY-003 — Required `[project]` metadata for publishing

**What.** Beyond the mandatory `name` and `version`, every package
published to PyPI should declare:

- `description` — one-line summary (shows in `pip search`, on PyPI landing page)
- `readme` — pointer to `README.md` with content-type
- `requires-python` — a floor like `">=3.11"` (PY-003 cross-references UVP-003)
- `license` — SPDX string per PEP 639 (PY-060)
- `classifiers` — Trove classifiers for discoverability
- `urls` — Homepage, Documentation, Repository, Changelog, Issues
- `authors` — name + email

**Why.** Missing fields cause silent quality loss:

1. **Missing `requires-python`** — `pip install` succeeds on incompatible Python versions, then crashes at import time with `SyntaxError` or `ImportError`. Users blame your package; the actual issue is they're on Python 3.9 and you use `match/case`.
2. **Missing `classifiers`** — PyPI search ranks by classifiers and filters by them ("show me only Python 3.12-compatible packages"). Without classifiers, you're invisible to filtered searches.
3. **Missing `urls`** — PyPI's "Project links" sidebar is blank. Users can't find your repo, issue tracker, or changelog. Looks abandoned.
4. **Missing `readme`** — PyPI shows "no description provided." Most adoption decisions happen on the PyPI landing page.

**How.**

```toml
[project]
name = "my-package"
version = "1.0.0"
description = "One-line summary, ~80 chars, used as PyPI headline."
readme = "README.md"
requires-python = ">=3.11"
license = "Apache-2.0"
authors = [
  {name = "Alice Smith", email = "alice@example.com"},
]
maintainers = [
  {name = "Bob Jones", email = "bob@example.com"},
]
keywords = ["http", "async", "api-client"]
classifiers = [
  "Development Status :: 5 - Production/Stable",
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Topic :: Software Development :: Libraries :: Python Modules",
  "Operating System :: OS Independent",
]

[project.urls]
Homepage = "https://my-package.example.com"
Repository = "https://github.com/alice/my-package"
Documentation = "https://my-package.readthedocs.io"
Changelog = "https://github.com/alice/my-package/blob/main/CHANGELOG.md"
Issues = "https://github.com/alice/my-package/issues"
```

Run `twine check dist/*` after building to catch most metadata
problems before upload.

**When NOT to apply.** Internal packages on private indexes can skimp
on classifiers and PyPI-shaped metadata; private index UIs typically
don't surface them. Public PyPI packages need all of the above.

---

## PY-004 — Pick `[build-system]` deliberately

**What.** Choose the build backend based on what your package
contains:

| Scenario | Backend | Build-system declaration |
|---|---|---|
| Pure Python, new project | `hatchling` (recommended default) | `requires = ["hatchling>=1.26"]`, `build-backend = "hatchling.build"` |
| uv-managed, minimal | `uv_build` (Astral's backend, zero-config) | `requires = ["uv_build"]`, `build-backend = "uv_build"` |
| Needs C/C++ extensions | `scikit-build-core` | `requires = ["scikit-build-core"]`, `build-backend = "scikit_build_core.build"` |
| Needs Rust extensions | `maturin` | `requires = ["maturin>=1.7,<2.0"]`, `build-backend = "maturin"` |
| Team standardized on Poetry | `poetry-core` | `requires = ["poetry-core>=2.0"]`, `build-backend = "poetry.core.masonry.api"` |
| Legacy migration | `setuptools` | `requires = ["setuptools>=68"]`, `build-backend = "setuptools.build_meta"` |

**Why.** Three failure modes from getting this wrong:

1. **No `[build-system]` table.** pip falls back to legacy `setuptools` with a deprecation warning, and the build behavior diverges from anything you can configure in `pyproject.toml`. Eventually pip will refuse the legacy fallback entirely.
2. **`setuptools` without configuration.** Auto-discovery includes the wrong files in the wheel — often `tests/` and `docs/` end up shipped to PyPI. Or, conversely, sub-packages are missed because `find_packages()` doesn't see them.
3. **`maturin` chosen for pure-Python projects.** Adds a Rust build dep nobody needs; build times balloon for no reason.

`hatchling` is the PyPA tutorial default and a safe choice for new
projects. It auto-discovers source layout, supports `dynamic =
["version"]` via the `hatch-vcs` plugin (PY-061), and has minimal
configuration burden.

**How.**

```toml
# Pure Python — recommended default
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

# With VCS-derived version (PY-061)
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[project]
dynamic = ["version"]

[tool.hatch.version]
source = "vcs"
```

```toml
# Rust extension (e.g. Astral's own tooling)
[build-system]
requires = ["maturin>=1.7,<2.0"]
build-backend = "maturin"

[tool.maturin]
features = ["pyo3/extension-module"]
```

**When NOT to apply.** Don't switch backends on a working established
project unless you have a concrete reason (need a feature the current
backend doesn't have, or your build is consistently broken). The
migration cost is real and rarely worth it for "hatchling is newer."

---

## PY-006 — `__init__.py`: explicit `__all__`, no side effects

**What.** Two related conventions for `__init__.py`:

1. If `__init__.py` re-exports names from submodules, list them in `__all__`.
2. Never perform I/O, mutate global state, configure logging, launch threads, or import heavy modules eagerly at import time.

**Why.** Two failure modes:

**Implicit re-exports break tooling and tests.**

```python
# WRONG — implicit exports
# src/mypackage/__init__.py
from mypackage.core import Foo, Bar
# No __all__. mypy's --no-implicit-reexport rejects this.
# Pyright in strict mode flags any user of Foo/Bar as an unknown import.
```

`from .submodule import *` (the worst form) makes `__all__`
maintenance impossible and lets internal names leak as part of your
public API by accident.

**Side-effect imports cause non-deterministic failures.**

```python
# WRONG — side effects at import time
# src/mypackage/__init__.py
import logging
logging.basicConfig(level=logging.DEBUG)   # contaminates every importing app

requests.get("https://license-check.com/...")   # network at import time

global_cache.populate()   # I/O before the user's code runs
```

The user `import mypackage` and... the application logs change.
Network call goes out. Database connection opens. None of which the
user explicitly asked for. Test isolation breaks (one test's import
side effects leak into the next).

**How.**

```python
# src/mypackage/__init__.py
"""Top-level package exports."""

from mypackage.client import Client
from mypackage.exceptions import APIError, RateLimitError

__all__ = [
    "Client",
    "APIError",
    "RateLimitError",
]
```

For a library that needs to *declare* logging (PY-052), the *only*
acceptable side effect is registering a `NullHandler`:

```python
# src/mypackage/__init__.py
import logging

logging.getLogger(__name__).addHandler(logging.NullHandler())

from mypackage.client import Client
__all__ = ["Client"]
```

**When NOT to apply.** Empty `__init__.py` is fine — and often the
right answer — when the package has no top-level public API and
users import submodules directly (`from mypackage.client import
Client`). The rule says "explicit `__all__` *if* re-exporting";
re-exporting is optional.

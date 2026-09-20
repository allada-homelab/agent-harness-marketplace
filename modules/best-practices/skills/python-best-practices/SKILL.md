---
name: python-best-practices
description: Use when working with Python projects — `.py` files, `pyproject.toml` (without `[tool.uv]`), `conftest.py`, `mypy.ini`, `pyrightconfig.json`, `.python-version` — or when the user asks about Python project layout, typing, linting, testing, async, logging, packaging, dependency auditing, or profiling. Mentions of pytest, mypy, pyright, basedpyright, ruff, structlog, hatch, or setuptools-scm are triggers. Covers the PY- rule family. For uv-specific patterns (`uv sync`, `[tool.uv]`, `uv.lock`) use uv-best-practices; for Python-in-Docker use containers-best-practices.
---

# Python best practices

A curated rule set for modern Python (3.10+) project work. Each rule
has a stable ID and a one-line summary; full **What / Why / How /
When-not-to-apply** entries live in `references/`.

This skill complements two adjacent ones:

- For **uv as a Python project tool** (pyproject `[tool.uv]`, lockfile, workspaces, CI, migration) — see [`uv-best-practices`](../uv-best-practices/) (`UVP-*` rule family).
- For **Python in containers** (multi-stage builds, cache mounts, system-Python installs) — see [`containers-best-practices`](../containers-best-practices/) (`UV-*` rule family).

This skill covers the rest: project layout, typing, linting, testing,
async, logging, packaging.

## When to apply this skill

Activate when any of these are true:

- The user is editing or generating `.py` files, `pyproject.toml` (outside the `[tool.uv]` section), `conftest.py`, `mypy.ini`, `pyrightconfig.json`, `.python-version`.
- The user asks about Python project structure, typing, linting, testing, async, logging, or packaging.
- The user mentions `pytest`, `mypy`, `pyright`, `ruff`, `structlog`, `hatch`, `setuptools-scm`, or related tooling.
- Reviewing a PR that touches Python files.

For uv-specific patterns (`uv sync`, `[tool.uv.workspace]`, `uv.lock`),
defer to `uv-best-practices`. For Python-in-Docker patterns
(`COPY --from=ghcr.io/astral-sh/uv`, multi-stage Python builds),
defer to `containers-best-practices`.

## Coverage

Topics the rule index below covers, for matching against the task at hand:

- **Project layout** — `src/` vs flat, `pyproject.toml` as single source of truth, `[project]` metadata, `[build-system]` choice, `__init__.py` discipline.
- **Typing & static analysis** — mypy / pyright / basedpyright / pyrefly / ty, strict mode, `Protocol` vs `ABC`, `TypedDict` vs `@dataclass` vs Pydantic, PEP 604/585/673 syntax, PEP 695 inline generics, `TypeIs` vs `TypeGuard` (PEP 742), `TypeForm` (PEP 747), deferred annotations (PEP 649/749).
- **Linting & formatting** — ruff replacing black + isort + flake8 + pyupgrade, rule selection, per-file ignores, pre-commit ordering, `RUF100`, range suppression, `DTZ` for naive datetimes.
- **Testing** — pytest 8.x+, `parametrize`, fixture scope, marker registration, `pytest-asyncio` vs `anyio`, `pytest-randomly` for order-dependence, hypothesis, coverage gates, ruff's `PT` family.
- **Async** — `TaskGroup` over `gather`, `asyncio.timeout` vs `wait_for`, the `create_task` GC trap, blocking-I/O detection, anyio for libraries, asyncio debug mode, free-threaded Python (PEP 703 / 779).
- **Logging** — stdlib vs structlog, `NullHandler` for libraries, `dictConfig`, contextvars, JSON to stdout, `QueueHandler` for low-latency async logging.
- **Packaging** — PEP 621 metadata, PEP 639 SPDX license, hatch-vcs versioning, Trusted Publishing (OIDC), PEP 740 build provenance attestations, PEP 702 `@warnings.deprecated`, PEP 723 inline script metadata, `datetime.utcnow` deprecation, sdist + wheel.
- **Security & profiling** — `pip-audit` / `uv audit` CVE scanning in CI; scalene / py-spy / mypyc decision-making before any native rewrite.

## How to use the rule index

1. Scan the relevant section(s) below for rule IDs that apply.
2. For each rule, open the corresponding `references/` file and read **only that rule's entry** — they're keyed by ID.
3. Cite the rule ID when explaining a change to the user (e.g. "`pyproject.toml` is the source of truth — PY-002").

## Rules — Project layout

See [`references/project-layout.md`](./references/project-layout.md).

- **PY-002** — `pyproject.toml` is the single source of truth — no `setup.py`, no `setup.cfg`, no `MANIFEST.in` for metadata.
- **PY-003** — Required `[project]` metadata for publishing: `description`, `readme`, `requires-python`, `license` (SPDX), `classifiers`, `urls`.
- **PY-004** — Pick `[build-system]` deliberately — `hatchling` is the sensible default for pure Python; `uv_build` for uv-managed pure-Python projects (PY-089); `maturin` / `scikit-build-core` for native extensions.
- **PY-006** — `__init__.py`: explicit `__all__` for re-exports; no side effects, no I/O, no global mutation at import time.

## Rules — Typing & static analysis

See [`references/typing.md`](./references/typing.md).

- **PY-010** — Use modern syntax: `X | Y` (PEP 604), `list[str]` / `dict[str, int]` (PEP 585), `Self` (PEP 673). No `Union[X, Y]`, no `typing.List`.
- **PY-011** — Default to `basedpyright` (or `pyright`) for new projects; stay on `mypy` for established codebases unless conformance gaps block you. `pyrefly` (Meta, stable 1.0) is a fast new option worth evaluating when you don't need mypy plugins; `ty` (Astral) is still beta.
- **PY-012** — Configure strict mode in `pyproject.toml` (`[tool.mypy] strict = true` or `[tool.pyright] typeCheckingMode = "strict"`).
- **PY-013** — `Protocol` for structural interfaces (duck typing with type safety); `abc.ABC` only when enforced inheritance is required.
- **PY-014** — Use `if TYPE_CHECKING:` for type-only imports + `from __future__ import annotations` at the top of files that need forward refs (on Python 3.14+ deferred evaluation is the default, so the future import is no longer needed for forward refs — see PY-080).
- **PY-015** — `TypedDict` for JSON / API shapes (no runtime cost); `@dataclass` for internal records; `pydantic.BaseModel` only at system boundaries that need runtime validation.
- **PY-016** — `# type: ignore[code]` and `# noqa: CODE` always with the explicit code — never bare. Bare ignores swallow future errors silently.
- **PY-069** — Prefer `TypeIs` (PEP 742) over `TypeGuard` for narrowing predicates — `TypeIs` narrows in both branches so `assert_never` exhaustiveness works.
- **PY-071** — Use PEP 695 inline generic syntax (`def foo[T]`, `class Foo[T]`, `type Alias = ...`) on Python 3.12+; PEP 696 defaults require 3.13.
- **PY-080** — On Python 3.14+, drop `from __future__ import annotations` — deferred annotation evaluation (PEP 649/749) is the default.
- **PY-081** — Use `TypedDict(closed=True)` / `extra_items=` for strict JSON shapes (PEP 728, Python 3.15+).
- **PY-082** — Use `TypeForm[T]` (PEP 747) for functions that accept a type expression at runtime, instead of `type[T]` or `Any`.

## Rules — Linting & formatting

See [`references/linting.md`](./references/linting.md).

- **PY-020** — Use `ruff` for both linting and formatting; drop `black`, `isort`, `flake8`, `pyupgrade`. Keep `mypy` / `pyright` (ruff isn't a type checker).
- **PY-021** — Recommended ruff rule selection: `E, W, F, B, I, UP, S, SIM, RUF`. Set `target-version` so `UP` rules respect your Python floor.
- **PY-022** — Per-file ignores for tests (`S101` asserts OK) and `__init__.py` (`F401` re-exports OK) via `[tool.ruff.lint.per-file-ignores]`.
- **PY-023** — Line length: 88 (ruff/black default). Don't fight the default unless your team already has a different standard.
- **PY-024** — pre-commit hook order: `ruff` (with `--fix`) **before** `ruff-format`. Lint fixes can produce output that needs reformatting.
- **PY-025** — Enable `RUF100` to flag unused `noqa` directives so suppression comments don't accumulate as dead weight.
- **PY-088** — Use ruff range suppression (`# ruff: disable[CODE]` / `# ruff: enable[CODE]`, ≥0.15) for multi-line blocks; always name the code.
- **PY-091** — Never `return` / `break` / `continue` out of a `finally` block (ruff `B012`; PEP 765 makes it a `SyntaxWarning` on 3.14).

## Rules — Testing (pytest 8.x+)

See [`references/testing.md`](./references/testing.md).

- **PY-030** — pytest config in `pyproject.toml [tool.pytest.ini_options]`; never `setup.cfg`. Set `markers`, `testpaths`, `addopts = "--strict-markers"`. On pytest 9+, prefer the native `[tool.pytest]` table and the `strict = true` mega-option.
- **PY-031** — Always `@pytest.mark.parametrize` over for-loops in test bodies — separate test IDs, isolated state, individually runnable.
- **PY-032** — Default fixtures to `function` scope; escalate to `session` only for genuinely expensive resources. Use `yield` for teardown.
- **PY-033** — Register every custom marker in `[tool.pytest.ini_options].markers`. Use `@pytest.mark.xfail(strict=True)` so unexpected passes fail loudly.
- **PY-034** — Async tests: pick `pytest-asyncio` *or* `anyio` plugin and configure one. Don't mix. Note `pytest-asyncio`'s default mode is `strict` (async tests need `@pytest.mark.asyncio` unless you set `asyncio_mode = "auto"`); the old `event_loop` fixture is removed in the 1.x line.
- **PY-035** — Coverage gate in `pyproject.toml [tool.coverage.report] fail_under = N` with `branch = true`. Treat 80% as a starting heuristic, not a magic number.
- **PY-074** — Add `pytest-randomly` to shuffle test order per run and detect order-dependent tests; pairs with function-scope fixtures (PY-032).
- **PY-086** — Enable ruff's `PT` family to mechanically enforce pytest style (bare `pytest.raises`, wrong `parametrize` shapes, unittest-style asserts).
- **PY-087** — Add `pytest-xdist` (`-n auto`) for parallel runs once the suite passes reliably under random order.

## Rules — Async (asyncio modern Python 3.11+)

See [`references/async.md`](./references/async.md).

- **PY-040** — `asyncio` for I/O-bound concurrency only; CPU-bound work goes to `ProcessPoolExecutor` via `loop.run_in_executor`.
- **PY-041** — Never call blocking I/O inside async (`requests`, `time.sleep`, sync DB drivers); enable `asyncio.run(..., debug=True)` / `PYTHONASYNCIODEBUG=1` in dev to detect.
- **PY-042** — `asyncio.run()` at the top level only; never nest. `nest_asyncio` is an antipattern outside Jupyter notebooks.
- **PY-043** — Prefer `asyncio.TaskGroup` (3.11+) over `asyncio.gather` for structured concurrency; always re-raise `CancelledError` after cleanup.
- **PY-044** — Wrap async generators in `contextlib.aclosing()` when iteration may break early — don't rely on GC to call `aclose()`.
- **PY-045** — Library code that must work on asyncio *and* Trio uses `anyio`; applications that own their runtime use `asyncio` directly.
- **PY-067** — Keep a strong reference to fire-and-forget `asyncio.create_task` results; tasks held only weakly can be GC'd mid-execution.
- **PY-068** — Prefer `async with asyncio.timeout(N):` (3.11+) over `asyncio.wait_for` for block-level timeouts; reserve `wait_for` for wrapping a single coroutine.
- **PY-079** — Free-threaded Python (PEP 703 / PEP 779) — informational guard-rail: not production-ready until your entire dep graph declares free-threading support. (3.14 reduced single-thread overhead to ~5–10%.)
- **PY-083** — On Python 3.14+, use `concurrent.interpreters.InterpreterPoolExecutor` for CPU-bound work needing process-like isolation at thread-like cost.
- **PY-084** — Use `asyncio.get_running_loop()`, never `asyncio.get_event_loop()` — the latter raises `RuntimeError` on 3.14+ with no running loop.
- **PY-085** — Introspect stuck async apps with `python -m asyncio ps <pid>` / `pstree <pid>` (3.14+) instead of adding instrumentation.

## Rules — Logging

See [`references/logging.md`](./references/logging.md).

- **PY-050** — Module-level `logger = logging.getLogger(__name__)` at the top of every file. Never call `logging.info(...)` (root logger) directly.
- **PY-051** — Pass positional args to log methods (`logger.info("user %s", user_id)`); never f-strings or `.format()`. Defers interpolation; preserves Sentry / aggregator grouping.
- **PY-052** — Libraries add only `logging.NullHandler()` and configure nothing else. Never call `basicConfig`, never set levels, never add handlers in library code.
- **PY-053** — Applications configure via `logging.config.dictConfig(...)` with `disable_existing_loggers: False`. Never use `basicConfig` outside one-off scripts.
- **PY-054** — `logger.exception("msg")` inside `except` blocks; `logger.error("msg", exc_info=True)` everywhere else. Outside `except`, `exception()` logs `NoneType: None`.
- **PY-055** — Propagate context (`request_id`, `user_id`) via `contextvars` + a `logging.Filter` (or `structlog.contextvars`). Redact secrets at the formatter/filter, not call sites.
- **PY-056** — Production: JSON to stdout, no in-process rotation — let the container/systemd handle log capture and rotation. Application code uses `structlog`; library code uses stdlib `logging`.
- **PY-076** — Wrap downstream handlers in `QueueHandler` / `QueueListener` so log I/O happens off the request thread / event loop. 3.12+ resolves handlers by name in `dictConfig`.

## Rules — Packaging & PyPI publishing

See [`references/packaging.md`](./references/packaging.md).

- **PY-060** — `license` is an SPDX string (PEP 639): `license = "MIT"`. The `{text = "MIT"}` / `{file = "LICENSE"}` table forms are deprecated.
- **PY-061** — Derive version from git tags via `hatch-vcs` (hatchling) or `setuptools-scm` (setuptools); declare `dynamic = ["version"]`. Don't hand-maintain a version in both `pyproject.toml` and `__init__.py`.
- **PY-062** — Publish from CI via **Trusted Publishing (OIDC)**, not API tokens. Use `pypa/gh-action-pypi-publish` with `id-token: write` permission.
- **PY-063** — Build with `uv build` or `python -m build` — both produce sdist + wheel together. Verify with `twine check dist/*` before upload.
- **PY-064** — Upload to TestPyPI first to catch metadata / README rendering issues. PyPI doesn't allow overwriting a release.
- **PY-065** — Dev dependencies go in `[project.optional-dependencies]` (or `[dependency-groups]` per UVP-001), never `[project.dependencies]`. End-users of your library shouldn't install pytest.
- **PY-066** — `warnings.warn(..., DeprecationWarning, stacklevel=2)` for public API deprecations. `stacklevel=2` points the warning at the caller, not your library's internals.
- **PY-070** — `@warnings.deprecated` (PEP 702, 3.13+ / `typing_extensions`) for type-checker-visible deprecations — flags call sites inline at edit time, not just at runtime.
- **PY-072** — Use PEP 723 inline script metadata (`# /// script` block) for standalone scripts with deps; `uv run script.py` consumes it directly.
- **PY-073** — `datetime.now(UTC)` / always-aware datetimes; `datetime.utcnow()` and `datetime.utcfromtimestamp()` are deprecated as of 3.12. Pair with ruff `DTZ` (opt-in per PY-021).
- **PY-075** — Enable PEP 740 build provenance attestations — automatic in `pypa/gh-action-pypi-publish` v1.11+ with `permissions: attestations: write`. Extends PY-062.
- **PY-089** — For uv-managed pure-Python projects, prefer the `uv_build` backend (zero-config, fast); see UVP-029 for the uv-side detail. Stay on hatchling for build hooks or non-uv workflows.

## Rules — Security

See [`references/packaging.md`](./references/packaging.md) (security-adjacent
rules live alongside packaging because that's where the CI pipeline owns
them).

- **PY-077** — Audit dependencies for known CVEs in CI with `pip-audit` (PyPA, OSV-backed) or `uv audit`. Don't gate releases on it silently — fail the build.
- **PY-090** — Pin dependency hashes (`uv lock`, or `--generate-hashes` for pip) and verify them with `--frozen` / `--require-hashes` in CI to blunt substitution attacks.

## Rules — Profiling & performance

See [`references/packaging.md`](./references/packaging.md).

- **PY-078** — Profile with `scalene` (local, line-level CPU + memory + native time) or `py-spy` (production sampling, attach by PID) *before* reaching for `mypyc`, Cython, or Rust extensions.

---
name: python-best-practices
description: Use when working with Python projects — `.py` files, `pyproject.toml` (without `[tool.uv]`), `conftest.py`, `mypy.ini`, `pyrightconfig.json`, `.python-version` — or when the user asks about Python project layout, typing, linting, testing, async, logging, packaging, dependency auditing, or profiling. Mentions of pytest, mypy, pyright, basedpyright, ruff, structlog, hatch, or setuptools-scm are triggers. Covers the PY- rule family. For uv-specific patterns (`uv sync`, `[tool.uv]`, `uv.lock`) use uv-best-practices; for Python-in-Docker use containers-best-practices.
user-invocable: false
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

## Applicability

Rules with no `when:` tag apply to every Python project. A tagged rule
applies only when its tag's check matches the repository. To audit a
repo, run each check once, then read the untagged rules plus the rules
whose tag matched. `packaged` and `publish` are the same tags, with the
same checks, as in `uv-best-practices`.

| Tag | Applies when | Detect |
|---|---|---|
| `asyncio` | The code uses asyncio | `grep -rlE '^\s*(import asyncio\|from asyncio )\|async def ' --include='*.py' .` |
| `ruff` | ruff is configured or run | `ls ruff.toml .ruff.toml`; `grep -l '^\[tool\.ruff' pyproject.toml`; `grep -l ruff .pre-commit-config.yaml` |
| `pytest` | The test suite uses pytest | `ls conftest.py tests/conftest.py pytest.ini pytest.toml`; `grep -lE '^\[tool\.pytest' pyproject.toml`; `grep -rl 'import pytest' --include='*.py' .` |
| `logging-config` | The code configures logging (handlers, levels, filters) | `grep -rlE 'logging\.(basicConfig\|config\.dictConfig\|config\.fileConfig)\|\.addHandler\(\|\.addFilter\(\|QueueHandler' --include='*.py' .` |
| `structlog` | The code uses structlog | `grep -rlE '^\s*(import\|from) structlog' --include='*.py' .` |
| `packaged` | The project declares a build backend | `grep -qE '^\[build-system\]\|^package *= *true' pyproject.toml` |
| `publish` | The repo uploads distributions | `grep -rlE 'uv publish\|gh-action-pypi-publish\|twine upload\|publish-url' .github/workflows .gitlab-ci.yml scripts/ Makefile justfile pyproject.toml` |

Rules were last checked on 2026-11-03 against CPython v3.15.2 (5e58eaa),
ruff 0.17.3 (ba65abf), pytest 9.2.0 (ae1d0ff), structlog 26.1.0 (8174a86),
python/typing main (1f8d6f8) and packaging.python.org main (44c9aac), by the
`rules-sweep` command in the `best-practices-maintainer` module; a new sweep
starts from those versions.

## Rules — Project layout

See [`references/project-layout.md`](./references/project-layout.md).

- **PY-002** — `pyproject.toml` is the single source of truth: all metadata goes in `[project]`, with no `setup.cfg` or `MANIFEST.in` for metadata; keep a `setup.py` only for programmatic build config (such as C extensions), with no metadata in it.
- **PY-003** — Required `[project]` metadata for publishing: `description`, `readme`, `requires-python`, `license` (SPDX), `classifiers`, `urls`. _(when: publish)_
- **PY-004** — Always declare `[build-system]`, because without it tools silently fall back to setuptools' legacy backend. Pick the backend deliberately: `hatchling` or `uv_build` (PY-089) for pure Python, `maturin` / `scikit-build-core` for native extensions, with values from the backend's own docs.
- **PY-110** — Use a `src/` layout with tests in a top-level `tests/`, so tests import the installed package rather than the unbuilt checkout on `sys.path`. _(when: packaged)_
- **PY-006** — `__init__.py`: explicit `__all__` for re-exports; no side effects, no I/O, no global mutation at import time.

## Rules — Typing & static analysis

See [`references/typing.md`](./references/typing.md).

- **PY-010** — Use modern syntax: `X | Y` (PEP 604), `list[str]` / `dict[str, int]` (PEP 585), `collections.abc.Callable`/`Sequence`/..., `Self` (PEP 673). No `Union`/`Optional`, `typing.List`, `typing.Text`; ruff `UP006`/`UP007`/`UP045`/`UP035`/`UP019` enforce it, since most old aliases emit no runtime warning (only `typing.ByteString` does).
- **PY-011** — Default to `pyright` (or `basedpyright`) for new projects; stay on `mypy` for established codebases unless conformance gaps block you. `pyrefly` (Meta, stable 1.0) is a fast new option worth evaluating when you don't need mypy plugins; `ty` (Astral) is still beta.
- **PY-012** — Configure strict mode in `pyproject.toml` (`[tool.mypy] strict = true` or `[tool.pyright] typeCheckingMode = "strict"`).
- **PY-013** — `Protocol` for structural interfaces (duck typing with type safety); `abc.ABC` only when enforced inheritance is required.
- **PY-119** — Mark every overriding method with `@override` (PEP 698) so a renamed or removed base method becomes a type error; basedpyright `reportImplicitOverride` flags unmarked overrides. _(requires python>=3.12 or typing-extensions>=4.4)_
- **PY-120** — Type any-value parameters as `object`, not `Any`, and ignored-return callbacks as `Callable[..., object]`, not `Any` or `None`; comment every remaining `Any` (ruff `ANN401`).
- **PY-121** — Take abstract, covariant parameter types (`Iterable`, `Sequence`, `Mapping`, `io.Reader`/`io.Writer`) and return concrete ones; an invariant `list[float]` parameter rejects `list[int]` and tuples.
- **PY-014** — Use `if TYPE_CHECKING:` for type-only imports + `from __future__ import annotations` at the top of files that need forward refs (on Python 3.14+ deferred evaluation is the default, so the future import is no longer needed for forward refs — see PY-080).
- **PY-015** — `TypedDict` for JSON / API shapes (no runtime cost); `@dataclass` for internal records; `pydantic.BaseModel` only at system boundaries that need runtime validation.
- **PY-016** — `# type: ignore[code]` and `# noqa: CODE` always with the explicit code — never bare. Bare ignores swallow future errors silently.
- **PY-069** — Prefer `TypeIs` (PEP 742) over `TypeGuard` for narrowing predicates — it narrows both branches so `assert_never` works. The narrowed type must be consistent with the parameter (take `Sequence`, not `list`), and the unchecked body must return True exactly for that type, so test it. _(requires python>=3.13 or typing-extensions>=4.10)_
- **PY-118** — End `match`/`if` chains over enums, `Literal`s and unions with `assert_never(x)`, and enable pyright `reportMatchNotExhaustive` or mypy `exhaustive-match`, so a new member is a type error. _(requires python>=3.11 or typing-extensions>=4.1)_
- **PY-071** — Use PEP 695 inline generic syntax (`def foo[T]`, `class Foo[T]`, `type Alias = ...`) on Python 3.12+. Variance is inferred; ruff `UP040`/`UP046`/`UP047` flag the legacy forms (all fixes unsafe); replace deprecated `AnyStr` and `TypeAlias`; PEP 696 defaults require 3.13. _(requires python>=3.12)_
- **PY-117** — Type forwarding decorators with `ParamSpec` (`Callable[P, R] -> Callable[P, R]`, wrapper `*args: P.args, **kwargs: P.kwargs`, `Concatenate` for added parameters) so the wrapped signature survives; not a `Callable[..., Any]`-bound TypeVar.
- **PY-080** — On Python 3.14+, drop `from __future__ import annotations` — deferred annotation evaluation (PEP 649/749) is the default. _(requires python>=3.14)_
- **PY-081** — Use `TypedDict(closed=True)` / `extra_items=` for strict JSON shapes (PEP 728, Python 3.15+). _(requires python>=3.15 or typing-extensions>=4.13)_
- **PY-082** — Use `TypeForm[T]` (PEP 747) for functions that accept a type expression at runtime, instead of `type[T]` or `Any`. _(requires python>=3.15 or typing-extensions>=4.13)_
- **PY-092** — On basedpyright, start from `typeCheckingMode = "recommended"` (or `"all"`), not `"strict"` — strict leaves every basedpyright-only rule off; downgrade per rule for untyped deps.
- **PY-093** — Under basedpyright, suppress with `# pyright: ignore[rule]`; pyright ignores the code in `# type: ignore[code]`, so it silences the whole line.
- **PY-122** — Type your own SQL and shell-command sinks as `LiteralString` (PEP 675) with values passed separately, so pyright/basedpyright reject strings built from runtime input (mypy does not enforce it). _(requires python>=3.11 or typing-extensions>=4.1)_
- **PY-098** — Use `sentinel("NAME")` (PEP 661) instead of `_MISSING = object()` — readable repr, survives copy/pickle, narrows in type checkers. _(requires python>=3.15 or typing-extensions>=4.16)_

## Rules — Linting & formatting

See [`references/linting.md`](./references/linting.md).

- **PY-020** — Use `ruff` for both linting and formatting; drop `black`, `isort`, `flake8`, `pyupgrade`. Keep `mypy` / `pyright` (ruff isn't a type checker).
- **PY-021** — Recommended ruff rule selection: `E, W, F, B, I, UP, S, SIM, RUF` (an explicit `select` replaces ruff's default set). Declare `requires-python` so ruff infers `target-version`; set it explicitly under `--config ruff.toml` or when no `requires-python` exists. _(when: ruff)_
- **PY-022** — Per-file ignores for tests (`S101` asserts OK) and `__init__.py` (`F401` re-exports OK) via `[tool.ruff.lint.per-file-ignores]`. _(when: ruff)_
- **PY-102** — One ruff config per scope: ruff never merges configs (closest wins), so every nested `[tool.ruff]` / `ruff.toml` / `.ruff.toml` sets `extend` to the root config. _(when: ruff)_
- **PY-023** — Line length: 88 (ruff/black default). Don't fight the default unless your team already has a different standard.
- **PY-024** — pre-commit hook order: `ruff` (with `--fix`) **before** `ruff-format`. Lint fixes can produce output that needs reformatting. _(when: ruff)_
- **PY-103** — Pass `--force-exclude` (or set `force-exclude = true`) when a local hook or script hands ruff explicit file paths; otherwise excluded generated/vendored files get linted and reformatted. _(when: ruff)_
- **PY-104** — Never apply ruff's unsafe fixes unattended: no `unsafe-fixes = true`, no `--unsafe-fixes` in hooks or CI; review with `--unsafe-fixes --diff` by hand. _(when: ruff)_
- **PY-025** — Enable `RUF100` to flag unused `noqa` directives so suppression comments don't accumulate as dead weight. _(when: ruff)_
- **PY-088** — Use ruff range suppression (`# ruff: disable[CODE]` / `# ruff: enable[CODE]`, ≥0.15) for multi-line blocks; always name the code and close every disable with a matching enable (`RUF104`). _(when: ruff)_ _(requires ruff>=0.15)_
- **PY-091** — Never `return` / `break` / `continue` out of a `finally` block (ruff `B012`; PEP 765 makes it a `SyntaxWarning` on 3.14).
- **PY-094** — Curate one explicit ruff `select` list (measure each family with `--statistics` first; prefer `select` over `extend-select`); never `ALL` or `preview = true` in long-lived projects. If one preview rule is needed, scope preview to `[tool.ruff.lint]` and set `explicit-preview-rules`. _(when: ruff)_

## Rules — Testing (pytest 8.x+)

See [`references/testing.md`](./references/testing.md).

- **PY-030** — pytest config in `pyproject.toml [tool.pytest.ini_options]`; never `setup.cfg`. Set `markers`, `testpaths`, `addopts = "--strict-markers"`. On pytest 9+, prefer the native `[tool.pytest]` table; use `strict = true` only with pytest locked, otherwise set `strict_config`, `strict_markers`, `strict_parametrization_ids` and `strict_xfail` individually. _(when: pytest)_
- **PY-111** — Set `addopts = ["--import-mode=importlib"]` so tests import the installed package, not the checkout via `sys.path`, and test basenames need not be unique; shared helpers go in the package, fixtures in `conftest.py`. _(when: pytest)_
- **PY-112** — `filterwarnings` lists `"error"` first and narrow ignores after (the last matching entry wins); never `--disable-warnings`. On pytest 9.1+, ratchet with `max_warnings` until `"error"` is feasible. _(when: pytest)_
- **PY-031** — Always `@pytest.mark.parametrize` over for-loops in test bodies — separate test IDs, every case runs, individually runnable. Values are passed without copying, so never mutate them in the test. _(when: pytest)_
- **PY-113** — Compare computed floats with `pytest.approx` (or `math.isclose`), never `==`. _(when: pytest)_
- **PY-032** — Default fixtures to `function` scope; escalate to `session` only for genuinely expensive resources. Use `yield` for teardown, with one state-changing action per fixture; `usefixtures` on a fixture is an error. _(when: pytest)_
- **PY-114** — Patch the name the code under test looks up (`mymodule.getcwd`), not the stdlib original; never patch builtins such as `open`; for code you own, pass the dependency in. _(when: pytest)_
- **PY-115** — Use `tmp_path` / `tmp_path_factory`, not the legacy `tmpdir` / `tmpdir_factory`; add `-p no:legacypath` to `addopts` so stray uses fail. _(when: pytest)_
- **PY-116** — Share fixtures via `conftest.py` or `pytest_plugins` in the top-level `conftest.py`; never import a fixture into a test module (unsupported, and ruff's F401 fix deletes the import). _(when: pytest)_
- **PY-033** — Register every custom marker in `[tool.pytest.ini_options].markers`. Make every xfail strict with `strict_xfail = true` (`xfail_strict` before pytest 9), and pass `raises=` so unrelated failures are not hidden as XFAIL. _(when: pytest)_
- **PY-034** — Async tests: pick `pytest-asyncio` *or* `anyio` plugin and configure one. Don't mix. Note `pytest-asyncio`'s default mode is `strict` (async tests need `@pytest.mark.asyncio` unless you set `asyncio_mode = "auto"`); the old `event_loop` fixture is removed in the 1.x line. _(when: pytest)_
- **PY-035** — Coverage gate in `pyproject.toml [tool.coverage.report] fail_under = N` with `branch = true`. Treat 80% as a starting heuristic, not a magic number.
- **PY-074** — Add `pytest-randomly` to shuffle test order per run and detect order-dependent tests; pairs with function-scope fixtures (PY-032). _(when: pytest)_
- **PY-086** — Enable ruff's `PT` family to mechanically enforce pytest style (`pytest.raises` on a broad exception without `match=`, wrong `parametrize` shapes, unittest-style asserts); don't list the removed PT004/PT005 in `ignore`. _(when: pytest)_
- **PY-087** — Add `pytest-xdist` (`-n auto`) for parallel runs once the suite passes reliably under random order. _(when: pytest)_

## Rules — Async (asyncio modern Python 3.11+)

See [`references/async.md`](./references/async.md).

- **PY-040** — `asyncio` for I/O-bound concurrency only; CPU-bound work goes to `ProcessPoolExecutor` via `loop.run_in_executor`. _(when: asyncio)_
- **PY-041** — Never call blocking I/O inside async (`requests`, `time.sleep`, sync DB drivers); in dev, turn on debug mode (`PYTHONASYNCIODEBUG=1`, `python -X dev`, `asyncio.run(..., debug=True)` or `loop.set_debug(True)`), show `ResourceWarning`, and set the `asyncio` logger to DEBUG to find them. _(when: asyncio)_
- **PY-101** — Code in another OS thread enters the event loop only through `loop.call_soon_threadsafe` and `asyncio.run_coroutine_threadsafe(coro, loop)`, never through `call_soon`/`create_task` or a direct call on an asyncio `Queue`/`Event`/`Future`. _(when: asyncio)_
- **PY-042** — Call `asyncio.run()` once, at the top level; never nest it (`asyncio.run() cannot be called from a running event loop`). Use `asyncio.Runner` for several top-level calls that share one loop. `nest_asyncio` is an antipattern outside Jupyter notebooks. _(when: asyncio)_
- **PY-043** — Prefer `asyncio.TaskGroup` (3.11+) over `asyncio.gather`, which does not cancel the other awaitables on failure. Put cleanup in `try/finally`; if you catch `CancelledError`, re-raise it, and call `uncancel()` only when you truly suppress it. _(when: asyncio)_
- **PY-044** — Wrap async generators in `contextlib.aclosing()` when iteration may break early — don't rely on GC to call `aclose()`. _(when: asyncio)_
- **PY-045** — Library code that must work on asyncio *and* Trio uses `anyio`; applications that own their runtime use `asyncio` directly. _(when: asyncio)_
- **PY-067** — Keep a strong reference to fire-and-forget `asyncio.create_task` and `asyncio.shield()` tasks, because the loop holds tasks only weakly and GC can collect them mid-execution. Prefer `TaskGroup`; with the background-set pattern, retrieve each task's exception in the done-callback. _(when: asyncio)_
- **PY-099** — Await or schedule every coroutine call; a bare `f()` creates a coroutine that never runs and only warns `coroutine ... was never awaited`. Type checkers flag it (`reportUnusedCoroutine`, mypy `unused-coroutine`). _(when: asyncio)_
- **PY-068** — Prefer `async with asyncio.timeout(N):` (3.11+) for block-level timeouts (`wait_for` uses it internally since 3.12) and catch `TimeoutError` outside the block. `asyncio.wait(timeout=)` and `as_completed(timeout=)` leave unfinished tasks running, so cancel them yourself. _(when: asyncio)_
- **PY-079** — Free-threaded Python (PEP 703 / PEP 779) — informational guard-rail: not production-ready until your entire dep graph declares free-threading support. (3.14 reduced single-thread overhead to ~5–10%.)
- **PY-083** — On Python 3.14+, use `concurrent.interpreters.InterpreterPoolExecutor` for CPU-bound work needing process-like isolation at thread-like cost. _(requires python>=3.14)_
- **PY-084** — Use `asyncio.get_running_loop()`, never `asyncio.get_event_loop()` — the latter raises `RuntimeError` on 3.14+ with no running loop. _(when: asyncio)_
- **PY-100** — Configure the event loop with `asyncio.run(..., loop_factory=...)` / `asyncio.Runner(loop_factory=...)`, not `set_event_loop_policy`, a policy subclass or `uvloop.install()`; the policy system is deprecated and slated for removal in 3.16. _(when: asyncio)_ _(requires python>=3.12)_
- **PY-085** — Introspect stuck async apps with `python -m asyncio ps <pid>` / `pstree <pid>` (3.14+) instead of adding instrumentation. _(when: asyncio)_ _(requires python>=3.14)_

## Rules — Logging

See [`references/logging.md`](./references/logging.md).

- **PY-050** — Module-level `logger = logging.getLogger(__name__)` at the top of every file. Never call `logging.info(...)` (root logger) directly: with no root handlers it runs `basicConfig()` for you, so the entry point's own `basicConfig` becomes a no-op. Ruff `LOG015` flags it.
- **PY-051** — Pass positional args to log methods (`logger.info("user %s", user_id)`); never f-strings, `.format()`, `%` or `+` (ruff `G004`/`G001`-`G003`). Defers the formatting (argument expressions still run, so guard expensive ones with `isEnabledFor`); preserves Sentry / aggregator grouping.
- **PY-106** — A helper that logs on its caller's behalf passes `stacklevel=2` (+1 per extra layer) so records report the caller's file, line and function, not the helper's.
- **PY-052** — Libraries add only `logging.NullHandler()` and configure nothing else. Never call `basicConfig`, never set levels, never add handlers in library code. _(when: packaged)_
- **PY-053** — Applications configure via `logging.config.dictConfig(...)` with `disable_existing_loggers: False`. Never use `basicConfig` outside one-off scripts: it is root-only and does nothing once root has handlers unless `force=True`. _(when: logging-config)_
- **PY-105** — Attach handlers once, on the root (or one top-level) logger, and let children propagate; a handler on a propagating child plus one on an ancestor emits every record twice. _(when: logging-config)_
- **PY-054** — `logger.exception("msg")` inside `except` blocks; outside `except`, pass the exception object: `logger.error("msg", exc_info=exc)`. `exception()` or `exc_info=True` outside `except` logs `NoneType: None`. Ruff `LOG004` / `LOG014` enforce it.
- **PY-055** — Propagate context (`request_id`, `user_id`) via `contextvars` + a `logging.Filter` (or `structlog.contextvars`). Redact secrets at the formatter/filter, not call sites. _(when: logging-config)_
- **PY-056** — Production: JSON to stdout, no in-process rotation — let the container/systemd handle log capture and rotation. Application code uses `structlog` (`WriteLoggerFactory`, `dict_tracebacks` before the renderer, no deprecated `AsyncBoundLogger`); library code uses stdlib `logging`. _(when: structlog)_
- **PY-076** — Wrap downstream handlers in `QueueHandler` / `QueueListener` so log I/O happens off the request thread / event loop. 3.12+ resolves handlers by name in `dictConfig`. _(when: logging-config)_

## Rules — Packaging & PyPI publishing

See [`references/packaging.md`](./references/packaging.md).

- **PY-060** — `license` is an SPDX string (PEP 639): `license = "MIT"`, with explicit `license-files`, no `License ::` classifiers, and a PEP 639-capable backend floor in `[build-system] requires`. The `{text = "MIT"}` / `{file = "LICENSE"}` table forms are deprecated. _(when: packaged)_ _(requires hatchling>=1.27 or setuptools>=77.0.3 or flit-core>=3.12 or pdm-backend>=2.4 or poetry-core>=2.2 or uv-build>=0.7.19)_
- **PY-061** — Derive version from git tags via `hatch-vcs` (hatchling) or `setuptools-scm` (setuptools) and list it in `dynamic = ["version"]`; if a version lives in both source and metadata, test that they agree; read other distributions' versions with `importlib.metadata.version()`. _(when: packaged)_
- **PY-062** — Publish from CI via **Trusted Publishing (OIDC)**, not API tokens: build in a separate job, publish job only downloads `dist/` and runs `pypa/gh-action-pypi-publish` with `id-token: write`; revoke the old API tokens. _(when: publish)_
- **PY-063** — Build with `uv build` or `python -m build` — both produce sdist + wheel together. Verify with `twine check dist/*` before upload; a `.md`/`.rst` readme sets its content type, other suffixes need `content-type`. _(when: packaged)_
- **PY-107** — Typed libraries ship an empty `py.typed` marker inside the import package (beside `__init__.py`) and confirm the wheel contains it — without it type checkers treat the package as untyped. _(when: packaged)_
- **PY-064** — Upload to TestPyPI once per release or release candidate (not every push) to catch metadata / README rendering issues. PyPI doesn't allow overwriting a release. _(when: publish)_
- **PY-065** — Dev, test and docs tools go in `[dependency-groups]` (PEP 735; `pip install --group` on pip 25.1+, `uv sync`), never `[project.dependencies]`; `[project.optional-dependencies]` is only for optional runtime features consumers install as extras.
- **PY-109** — Build aggregate extras by self-reference (`all = ["your-project[gui,cli]"]`) instead of copying each extra's dependencies. _(when: packaged)_
- **PY-066** — `warnings.warn(..., DeprecationWarning, stacklevel=2)` for public API deprecations. `stacklevel=2` points the warning at the caller, not your library's internals.
- **PY-070** — `@warnings.deprecated` (PEP 702, 3.13+ / `typing_extensions`) for type-checker-visible deprecations — flags call sites inline at edit time, not just at runtime. _(requires python>=3.13 or typing-extensions>=4.5)_
- **PY-072** — Use PEP 723 inline script metadata (`# /// script` block) for standalone scripts with deps; `uv run script.py` consumes it directly.
- **PY-108** — Never work around `externally-managed-environment` with `--break-system-packages` / `PIP_BREAK_SYSTEM_PACKAGES=1`; create a virtual environment instead.
- **PY-073** — `datetime.now(UTC)` / always-aware datetimes; `datetime.utcnow()` and `datetime.utcfromtimestamp()` are deprecated as of 3.12. Pair with ruff `DTZ` (opt-in per PY-021).
- **PY-075** — Get PEP 740 build provenance attestations by publishing via Trusted Publishing with `pypa/gh-action-pypi-publish` v1.11.0+ — on by default with only `id-token: write`; don't set `attestations: false`. Extends PY-062. _(when: publish)_
- **PY-089** — For uv-managed pure-Python projects, prefer the `uv_build` backend (zero-config, fast); see UVP-029 for the uv-side detail. Stay on hatchling for build hooks or non-uv workflows. _(when: packaged)_

## Rules — Security

See [`references/packaging.md`](./references/packaging.md) (security-adjacent
rules live alongside packaging because that's where the CI pipeline owns
them).

- **PY-077** — Audit dependencies for known CVEs in CI with `pip-audit` (PyPA, OSV-backed) or `uv audit`. Don't gate releases on it silently — fail the build.
- **PY-090** — Pin dependency hashes (`uv lock`, or `--generate-hashes` for pip) and verify them with `uv sync --locked` / `--require-hashes` in CI to blunt substitution attacks.

## Rules — Profiling & performance

See [`references/packaging.md`](./references/packaging.md).

- **PY-078** — Profile with `scalene` (local, line-level CPU + memory + native time) or `py-spy` (production sampling, attach by PID) — or, on Python 3.15+, the stdlib `profiling.sampling` (Tachyon) — *before* reaching for `mypyc`, Cython, or Rust extensions.
- **PY-095** — Use `lazy import` / `lazy from ... import` (PEP 810) for heavy modules most runs don't use; module scope only, never around side-effect imports. _(requires python>=3.15)_

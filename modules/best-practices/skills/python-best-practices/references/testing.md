# PY testing rules

Detailed entries for `PY-030..PY-039` plus `PY-074`
(`pytest-randomly`). Each follows the four-part **What / Why /
How / When NOT to apply** shape.

Citations point at the [pytest docs](https://docs.pytest.org/en/stable/),
[coverage.py docs](https://coverage.readthedocs.io/),
[anyio testing docs](https://anyio.readthedocs.io/en/stable/testing.html),
[pytest deprecations](https://docs.pytest.org/en/stable/deprecations.html),
and [pytest-randomly](https://pypi.org/project/pytest-randomly/).

---

## PY-030 — pytest config in `pyproject.toml [tool.pytest.ini_options]`

**What.** All pytest config lives in `pyproject.toml` under
`[tool.pytest.ini_options]`. Never `setup.cfg` (different parser,
hard-to-track bugs). On pytest 9.0+, the newer `[tool.pytest]`
section with native TOML types is preferred; `[tool.pytest.ini_options]`
remains the safe back-compat form through pytest 8.x. Pytest 9 also adds
`strict = true` — a single mega-option bundling `strict_markers` +
`strict_config` + `strict_parametrization_ids` + `strict_xfail` — prefer
it to spelling those flags out individually in `addopts`, but only with
pytest pinned in the lockfile: "If pytest adds new strictness options in
the future, they will also be enabled in strict mode. Therefore, you
should only enable strict mode if you use a pinned/locked version of
pytest" ([pytest reference — strict](https://docs.pytest.org/en/stable/reference/reference.html#confval-strict)).
An unpinned pytest can otherwise turn a new release into a red suite.

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --strict-markers --strict-config"
markers = [
  "slow: marks tests that hit network or take >1s",
  "integration: requires running services",
]
asyncio_mode = "auto"        # if using pytest-asyncio (PY-034)
filterwarnings = [
  "error",                    # treat warnings as errors by default
  "ignore::DeprecationWarning:third_party_lib.*",
]
```

**Why.** Three failure modes:

1. **`setup.cfg` silently mis-parses list options.** Markers, addopts, and filterwarnings often end up wrong because `setup.cfg`'s parser treats them as strings, not lists. Tests run with broken config and nobody notices.
2. **Multiple config files cause precedence confusion.** pytest looks for `pytest.ini`, `pyproject.toml`, `tox.ini`, `setup.cfg` in that order; whichever wins becomes the source of truth, and the others silently lose. Picking one is the only safe path.
3. **`addopts = --strict-markers`** is the single most important pytest flag — without it, a typo in `@pytest.mark.integartion` silently doesn't filter, so the test runs in every suite. With it, pytest fails with "unknown marker."

**How.** Two real shapes:

```toml
# pytest 8.x — compatible form
[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
addopts = [
  "--strict-markers",
  "--strict-config",
  "-q",
  "--tb=short",
]
markers = [
  "slow: tests that take >1s; run with pytest -m slow",
  "integration: tests requiring external services",
  "smoke: quick subset for PR gating",
]
filterwarnings = [
  "error",
  "ignore::pytest.PytestUnraisableExceptionWarning",
  "ignore::DeprecationWarning:botocore.*",
]
```

```toml
# pytest 9.0+ — native TOML types
[tool.pytest]
minversion = "9.0"
testpaths = ["tests"]
strict_markers = true
strict_config = true
```

**When NOT to apply.** Legacy repos still on `pytest.ini` or
`setup.cfg` — migration is straightforward; do it when you have any
reason to touch test config.

---

## PY-031 — Always `@pytest.mark.parametrize` over for-loops

**What.** When testing the same logic across multiple input/output
pairs, use `@pytest.mark.parametrize`, not a for-loop inside the
test body.

```python
# RIGHT
@pytest.mark.parametrize("x,expected", [
    (0, 0),
    (1, 1),
    (-1, 1),
    pytest.param(2**31, 2**31, id="large"),
    pytest.param(-1, 1, id="negative", marks=pytest.mark.xfail(reason="bug #123")),
])
def test_abs(x, expected):
    assert abs(x) == expected
```

**Why.** Four concrete failures from for-loops:

1. **Stops at the first failure.** A for-loop hits `assert` and stops; the next 5 cases aren't checked. With parametrize, each case is its own test — they all run and all report independently.
2. **Can't be run individually.** `pytest tests/test_abs.py::test_abs[case3]` doesn't work with loops. With parametrize, each case has a generated test ID you can target.
3. **Per-case markers.** Want to xfail one specific case? With a loop, you put `if x == -1: pytest.xfail(...)` inside the body — ugly and easy to miss. With `pytest.param(..., marks=...)`, each case carries its own marks declaratively.
4. **Mutation across iterations.** If parameters are mutable (lists, dicts) and a test mutates them, the next iteration in a loop sees the mutation. Parametrize creates fresh values per test invocation.

**How.**

```python
# Basic
@pytest.mark.parametrize("input,expected", [
    ("foo", 3),
    ("hello", 5),
    ("", 0),
])
def test_len(input, expected):
    assert len(input) == expected

# Per-case IDs and marks
@pytest.mark.parametrize("path", [
    pytest.param("/tmp", id="absolute"),
    pytest.param("~/dir", id="home", marks=pytest.mark.skipif(WIN, reason="POSIX")),
    pytest.param(".", id="cwd"),
])
def test_resolve(path):
    ...

# Multi-axis: cartesian product
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
@pytest.mark.parametrize("strict", [True, False])
def test_decode(encoding, strict):
    # 2 × 2 = 4 test invocations
    ...

# Generated from a list
@pytest.mark.parametrize("case", [
    Case(input="a", expected=1),
    Case(input="b", expected=2),
], ids=lambda c: c.input)
def test_from_dataclass(case):
    ...
```

**When NOT to apply.** A single test that needs to *demonstrate*
sequential operations (state machine, multi-step flow). For those,
the test body is procedural by nature, not a series of independent
cases. Parametrize is for *independent* repetitions.

---

## PY-032 — Default fixtures to `function` scope; use `yield` for teardown

**What.** Two related rules:

1. **Default fixture scope is `function`** (the safest). Escalate to `module` or `session` only for genuinely expensive resources (DB connections, Docker containers).
2. **Use `yield` for teardown** — never a try/finally wrapping the whole fixture body.

```python
import pytest

# function scope (the default) — fresh per test
@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path  # tmp_path is itself a pytest-builtin fixture

# session scope — expensive resource, shared
@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine(TEST_DSN)
    yield engine        # teardown runs even if tests fail
    engine.dispose()

# function scope — depends on session-scoped fixture
@pytest.fixture
def db_session(db_engine):
    conn = db_engine.connect()
    yield conn
    conn.rollback()
    conn.close()
```

**Why.** Two failure modes:

1. **Aggressive scope causes order-dependent failures.** A
   `session`-scoped fixture that mutates shared state (a temp dir,
   a DB row) leaks across tests. Test order changes (new test
   added, alphabetical order shifts) cause spurious failures that
   are impossible to reproduce in isolation. Function scope is
   immune to this by default.
2. **try/finally instead of yield runs teardown only on success.**
   If the setup-side of the fixture raises (e.g. `engine =
   create_engine(...)` fails), `finally:` runs — but anything
   between the failure and the `finally` doesn't. With yield, the
   "before yield" code is setup; "after yield" is teardown; pytest
   guarantees teardown runs after a successful setup even when the
   *test* fails.

**How.**

```python
# Decomposed fixtures — session-scoped expensive setup,
# function-scoped per-test transaction
@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine(TEST_DSN)
    yield engine
    engine.dispose()

@pytest.fixture
def db(db_engine):
    """Per-test transaction that rolls back."""
    conn = db_engine.connect()
    tx = conn.begin()
    try:
        yield conn
    finally:
        tx.rollback()
        conn.close()

# Factory fixture pattern
@pytest.fixture
def make_user(db):
    created = []
    def _factory(**kwargs):
        user = User(**kwargs)
        db.add(user)
        created.append(user)
        return user
    yield _factory
    # Optional cleanup (transaction rollback handles it in this case)
```

**`autouse=True`** is a legitimate but easy-to-overuse feature.
Use it for setup that genuinely applies to every test (configuring
logging, seeding a global rng) — not as a hack to avoid declaring
fixture deps.

**Deprecation note:** `@pytest.mark.usefixtures()` on a fixture
function (not a test) is deprecated in pytest 8 and will error in
a future version.

**When NOT to apply.** When the fixture is genuinely a
constant-time operation (parsing a fixed string, creating a
hardcoded value), `function` scope is overkill — but the cost is
microseconds and the safety is real. Default to `function`; escalate
only when you measure cost.

---

## PY-033 — Register custom markers; `--strict-markers`; `xfail(strict=True)`

**What.** Three intertwined rules:

1. Every custom marker (`@pytest.mark.slow`, `@pytest.mark.integration`) must be declared in `[tool.pytest.ini_options].markers`.
2. `--strict-markers` in `addopts` so an unknown marker fails the test run instead of silently passing.
3. `@pytest.mark.xfail(strict=True)` so unexpected passes (a test marked xfail that *succeeds*) fail the suite.

```toml
[tool.pytest.ini_options]
addopts = "--strict-markers"
markers = [
  "slow: marks tests that take >1s",
  "integration: requires external services",
  "smoke: critical-path subset",
]
```

```python
@pytest.mark.xfail(strict=True, reason="Bug #1234 — fix landing in v2")
def test_known_broken():
    assert buggy_function() == "fixed"   # currently returns "broken"
```

**Why.** Two failure modes:

1. **Typo'd marker runs in every suite.** `@pytest.mark.integartion` (typo) doesn't match `pytest -m integration` (correct), so the test isn't filtered out. It runs in unit-test runs *and* integration runs. Without `--strict-markers`, pytest just emits a warning that nobody reads.
2. **`xfail` without `strict=True` is silent tech debt.** A test marked xfail that starts passing stays marked xfail forever, because pytest reports "XPASS (xfail)" as success. Three months later, when the underlying bug *regresses*, the test fails again — and you've lost the signal that it ever started working.

**How.**

```toml
[tool.pytest.ini_options]
addopts = [
  "--strict-markers",
  "--strict-config",       # also good — typos in config fail
]
markers = [
  "slow: takes >1s; run with -m slow",
  "integration: needs external services (docker compose up)",
  "smoke: small fast subset for PR gates",
  "skipif_no_gpu: skipped when CUDA not available",
]
```

```python
@pytest.mark.slow
def test_full_corpus_ingestion():
    ...

@pytest.mark.xfail(strict=True, reason="bug #4567")
def test_known_broken():
    ...

# pytest -m "not slow"  → skip slow ones
# pytest -m "slow and integration"  → boolean combinations
```

**When NOT to apply.** Built-in markers (`@pytest.mark.skip`,
`@pytest.mark.skipif`, `@pytest.mark.parametrize`,
`@pytest.mark.xfail`) don't need registration — they're built-in.
The rule applies to *custom* markers you introduce.

---

## PY-034 — Async tests: pick `pytest-asyncio` *or* `anyio`, not both

**What.** Two valid async-test plugins. Pick one; configuring both
with `auto` mode causes conflicts. Note `pytest-asyncio`'s **default
mode is `strict`**, not `auto` — async tests need an explicit
`@pytest.mark.asyncio` unless you set `asyncio_mode = "auto"` (as shown
below). The `event_loop` fixture was **removed in the pytest-asyncio 1.x
line**; customize the loop via the plugin's fixture factories, not by
redefining `event_loop`.

| Plugin | Use when |
|---|---|
| `pytest-asyncio` with `asyncio_mode = "auto"` | Pure asyncio codebase; simplest setup |
| `anyio` plugin (`@pytest.mark.anyio`) | Library code that must work on asyncio AND Trio, or when you need context-var preservation across fixtures |

**Why.** Two failure modes:

1. **Plugin conflict.** With both plugins installed and both having `auto` mode active, every `async def test_...` is collected by both; the test runs twice (or fails ambiguously). The error messages are unhelpful (`fixture 'event_loop' not found` or similar).
2. **anyio preserves context vars across fixture phases; pytest-asyncio doesn't.** This matters when you're testing code that uses `contextvars` (request IDs, current user, transaction state) — pytest-asyncio runs each async fixture phase in a new task, losing the context. anyio preserves it across setup → test → teardown. If your code uses contextvars, anyio is the correct choice.

**How.** Pure asyncio path:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"           # all async test fns auto-marked

[project.optional-dependencies]
dev = [..., "pytest-asyncio>=0.26"]
```

(Older pytest-asyncio releases configured the loop policy via the
now-deprecated `asyncio_mode` *ini key spelling*; current docs use
the same key but the plugin emits a `DeprecationWarning` if you pin
a pre-0.23 version that still recognized alternate spellings. On
0.26+, the example above is the supported form. If you upgrade
across the boundary, re-read the plugin's CHANGELOG for any
fixture-scope semantics changes — pytest-asyncio has shifted those
several times.)

```python
# async tests just work
async def test_fetch():
    result = await fetch_data()
    assert result.status == "ok"
```

anyio path (library or contextvars-heavy code):

```toml
# remove asyncio_mode from pytest config

[project.optional-dependencies]
dev = [..., "anyio>=4.0", "pytest>=8.0"]
```

```python
import pytest

@pytest.mark.anyio
async def test_fetch():
    result = await fetch_data()
    assert result.status == "ok"

# Run against both backends in a matrix:
@pytest.fixture(params=["asyncio", "trio"])
def anyio_backend(request):
    return request.param
```

**When NOT to apply.** Codebases with no async code don't need
either. Don't add complexity until you have async functions to
test.

---

## PY-035 — Coverage gate in `pyproject.toml [tool.coverage.report]`

**What.** Configure coverage threshold in `pyproject.toml` so the
gate runs locally too (not just in CI), and enable branch coverage
(more honest than line coverage):

```toml
[tool.coverage.report]
fail_under = 85
show_missing = true
exclude_lines = [
  "pragma: no cover",
  "if TYPE_CHECKING:",
  "raise NotImplementedError",
  "if __name__ == .__main__.:",
]

[tool.coverage.run]
branch = true                    # check both branches of if/else
source = ["src/mypackage"]
omit = [
  "*/migrations/*",
  "src/mypackage/_generated.py",
]
```

**Why.** Three reasons:

1. **CI-only gates are easy to game.** A developer can push code with no tests, run "skip coverage" locally, and have it be CI's problem. When the gate runs locally (via `pytest --cov` reading the same config), developers see the impact during dev.
2. **Branch coverage exposes happy-path bias.** A function with `if x: return Y else: return Z` reports 100% line coverage even when tests only exercise one branch. Branch coverage flags the other branch as uncovered.
3. **`exclude_lines` keeps the metric honest.** `if TYPE_CHECKING:` blocks never run at runtime — they're always 0% line coverage and shouldn't count. Same for `NotImplementedError` placeholders and `if __name__ == "__main__":` entrypoints.

**Don't treat the number as magic.** A 95%-covered module with 0%
coverage on the actual error-handling code is worse than 75%
coverage that hits both the happy path and the error path. Treat
the gate as a floor, not a ceiling.

**How.**

```toml
[tool.coverage.run]
branch = true
source = ["src/mypackage"]
parallel = true                  # if running with pytest-xdist
omit = [
  "src/mypackage/__main__.py",
  "src/mypackage/_version.py",
]

[tool.coverage.report]
fail_under = 85
show_missing = true
skip_covered = true              # don't list 100%-covered files in report
exclude_lines = [
  "pragma: no cover",
  "if TYPE_CHECKING:",
  "raise NotImplementedError",
  "if __name__ == .__main__.:",
  "\\.\\.\\.",                   # ellipsis in Protocols / abstract methods
]
```

```bash
# Local — gate enforced
uv run pytest --cov

# In CI — same config, plus reports
uv run pytest --cov --cov-report=xml --cov-report=term-missing
```

**When NOT to apply.** Brand new projects with <100 lines of code
— coverage metrics are noisy at small sizes. Set the gate once you
have meaningful surface area. Single-script tooling doesn't need a
coverage gate either.

---

## PY-074 — Add `pytest-randomly` to detect order-dependent tests

**What.** Add [`pytest-randomly`](https://pypi.org/project/pytest-randomly/)
to dev dependencies. It shuffles test order each run, prints the
seed it used, and lets you reproduce any failure with that seed.

```toml
[project.optional-dependencies]
dev = [..., "pytest-randomly"]
```

```
$ pytest
Using --randomly-seed=2718281828
...
```

Reproduce a CI failure locally:

```
$ pytest --randomly-seed=2718281828
$ pytest --randomly-seed=last        # replay the last local run's seed
```

**Why.** Order-dependent tests are a silent killer:

1. **They pass in CI on the order CI happens to run them, then break the moment someone adds a new test in alphabetical sort position.** The new test was completely unrelated; the *real* problem was that `test_a` left state in a module global that `test_b` happened to read in the order they ran. Without randomization, this hides for months.
2. **They're invisible without active detection.** Function-scope fixtures (PY-032) and proper teardown *prevent* most order dependencies — but enforcement is opt-in. Randomization is the **detection** side: if your tests pass under random order across many seeds, they're genuinely independent. If they fail, you've found real coupling.
3. **CI reproduction is solved.** Without a seed, "the test failed once in CI but passes locally" is a debugging nightmare. With pytest-randomly, CI prints the seed in the test header; copying it into `--randomly-seed=...` reproduces deterministically.

Pair with PY-032 (function-scope fixtures): function-scope is the
*prevention*; pytest-randomly is the *detection*. Together they
keep test isolation honest. Pair also with PY-033 (xfail strict +
strict-markers) — same family of "make tests tell the truth about
themselves."

**How.**

```toml
[project.optional-dependencies]
dev = ["pytest>=8", "pytest-randomly"]

[tool.pytest.ini_options]
addopts = ["--strict-markers", "--strict-config"]
# pytest-randomly auto-activates; no extra config needed
```

```bash
# Normal run — new shuffle each time, seed printed in header
pytest

# Reproduce a specific run
pytest --randomly-seed=2718281828

# Reproduce the last local run
pytest --randomly-seed=last

# Disable shuffling for a specific debugging session
pytest -p no:randomly
```

If a test genuinely *must* run in a specific order (e.g. it depends
on a module-import side effect that only happens once), express
that with a fixture (`autouse=True` setup, conftest-level
initialization) rather than relying on order. The whole point of
the rule is to *prevent* that pattern from sneaking in undetected.

**When NOT to apply.** Two narrow cases:

1. **Doctests or notebook-style tests** where ordering reflects an intentional narrative (rare in modern Python; usually doctest examples are independent). For those, run them with `-p no:randomly` in their own pytest invocation.
2. **Tightly coupled smoke tests for an integration script** — sometimes a 5-step "create → fetch → modify → re-fetch → delete" test is intentionally sequential. Express that as **one** test with multiple steps in the body, not five separate `test_step1`, `test_step2`, ... functions that secretly depend on each other.

## PY-086 — Enable ruff's `PT` family to enforce pytest style mechanically

**What.** Ruff's `PT` rules (from flake8-pytest-style) catch common
pytest antipatterns: `unittest`-style assertions instead of plain
`assert`, a bare `pytest.raises(...)` with no `match=`, wrong
`@pytest.mark.parametrize` argument shapes, and similar. Add `"PT"` to
your ruff `select`.

**Why.** PY-030–PY-035 describe pytest *structure*; `PT` enforces it
automatically so reviewers don't have to. It's the mechanical complement
to the judgment rules — cheap, consistent, and catches drift as the suite
grows.

**How.**

```toml
[tool.ruff.lint]
extend-select = ["PT"]
ignore = ["PT003", "PT004", "PT013"]   # widely considered over-opinionated
```

**When NOT to apply.** Non-pytest test suites (`unittest`, `nose`) — the
rules assume pytest idioms. A few `PT` rules are contentious; ignore the
specific ones your team disagrees with rather than dropping the family.

---

## PY-087 — Add `pytest-xdist` for parallel runs once the suite is order-independent

**What.** `pytest-xdist` with `-n auto` distributes tests across all CPU
cores, cutting wall-clock time on large suites. It requires genuinely
isolated tests — no shared mutable files, no `tmp_path` races.

**Why.** A large serial suite is a CI bottleneck. xdist parallelizes it,
but only safely once tests don't depend on execution order or shared
state — so it pairs with function-scope fixtures (PY-032) and
`pytest-randomly` (PY-074), which surface hidden ordering deps. Add
`parallel = true` under `[tool.coverage.run]` when combining with
coverage.

**How.**

```bash
pytest -n auto                 # one worker per core
```

```toml
[tool.coverage.run]
parallel = true                # required when measuring coverage under xdist
```

**When NOT to apply.** Small suites where worker startup outweighs the
saving. And don't reach for xdist to paper over flakiness — if tests fail
under random order (PY-074), fix the isolation first; parallelism only
makes hidden coupling fail more confusingly.

---

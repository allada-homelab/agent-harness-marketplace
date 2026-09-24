# PY linting rules

Detailed entries for `PY-020..PY-029`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the [ruff docs](https://docs.astral.sh/ruff/),
the [ruff-pre-commit repo](https://github.com/astral-sh/ruff-pre-commit),
and [ruff rules index](https://docs.astral.sh/ruff/rules/).

---

## PY-020 — Use `ruff` for both lint and format; drop `black`, `isort`, `flake8`, `pyupgrade`

**What.** `ruff` and `ruff format` together cover what was
historically four tools. Remove all four from dev dependencies; keep
type checkers (`mypy` / `pyright`) — ruff is not a type checker.

**Why.** Three concrete wins:

1. **Speed.** Ruff is written in Rust and runs ~10-100x faster than the Python-implemented equivalents. On large codebases the difference is "instant" vs. "go get coffee."
2. **Single config.** One `[tool.ruff]` block in `pyproject.toml` instead of four tool sections that mutually contradict each other (black says 88 chars, flake8's `E501` defaults to 79, isort and black argue about import order).
3. **No format/lint conflicts.** Running `black` and `ruff format` together (or `isort` and ruff's `I` rules) produces a diff loop where each tool undoes the other's changes. Pick ruff for both; the conflict disappears.

The trap: people install ruff but keep black/isort "just in case."
This is the worst-of-both — you pay for two formatters, you get
format conflicts.

**How.**

```bash
# Remove the old tools
uv remove --dev black isort flake8 pyupgrade

# Add ruff
uv add --dev ruff
```

```toml
# pyproject.toml — minimum viable ruff config
[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.lint]
select = [
  "E", "W", "F",        # pycodestyle + Pyflakes (baseline)
  "B",                   # bugbear
  "I",                   # isort
  "UP",                  # pyupgrade
  "S",                   # flake8-bandit (security)
  "SIM",                 # simplify
  "RUF",                 # ruff-specific
]

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["S101"]   # asserts only in tests; keep S101 on in src (PY-022)

[tool.ruff.format]
quote-style = "double"
```

```bash
# Daily workflow
ruff check . --fix       # lint with auto-fix
ruff format .            # format
```

**When NOT to apply.** Plugins. Some flake8 plugins
(`flake8-mypy`, `flake8-typing-imports`) have no ruff equivalent.
If your project depends on one of those, keep flake8 *only for that
plugin*. Don't keep flake8 for "general linting" — ruff covers that.

---

## PY-021 — Recommended ruff rule selection + `target-version`

**What.** Ruff's default selection (`E`, `F`) is too minimal. A
sensible baseline for new projects:

```toml
[tool.ruff]
target-version = "py311"     # critical — UP rules respect this

[tool.ruff.lint]
select = [
  "E",     # pycodestyle errors
  "W",     # pycodestyle warnings
  "F",     # Pyflakes (unused imports, undefined names)
  "B",     # flake8-bugbear (common bugs: mutable default args, etc.)
  "I",     # isort (import order)
  "UP",    # pyupgrade (modernize syntax)
  "S",     # flake8-bandit (security)
  "SIM",   # flake8-simplify
  "RUF",   # Ruff-specific
]
```

**Why.** Each family catches a different class of real bug:

- **`B` (bugbear)** — catches `def foo(x=[])` (mutable default arg), `except:` (bare except), `assert isinstance` discipline, and other footguns. The single highest-value non-default family.
- **`I` (isort)** — sorted, grouped imports. Reduces merge conflicts in import blocks.
- **`UP` (pyupgrade)** — `Union[X, Y]` → `X | Y`, `typing.List` → `list`, `super(MyClass, self)` → `super()`. Enforces PY-010 mechanically.
- **`S` (bandit)** — flags `pickle.loads`, `eval`, `subprocess(shell=True)`, hardcoded passwords. Real security wins.
- **`SIM` (simplify)** — flags `if x == True:` → `if x:`, redundant `if/else` patterns. Mostly cosmetic but reduces code volume.
- **`RUF`** — ruff-specific rules including `RUF100` (unused noqa, see PY-025).

`target-version` is critical: without it, `UP` rules suggest 3.12+
syntax for a 3.9-targeted library, breaking the build for users on
older Python. Match it to your `requires-python` floor.

**How.** The config above is a good starting point. Tune as needed:

```toml
[tool.ruff.lint]
select = [...as above...]
ignore = [
  "E501",     # let formatter handle line length (ruff format wraps long lines)
  "S104",     # binding to 0.0.0.0 is OK in container apps
  "SIM108",   # ternary if/else — sometimes if/else reads better
]
```

**Families to consider but NOT enable by default:**

- **`PL` (Pylint port)** — Hundreds of rules with many false positives for typical projects. Enable selectively: maybe `PLR2004` (magic value comparison) and `PLW1641` (eq without hash) but not the whole family.
- **`ANN` (flake8-annotations)** — Requires type annotations everywhere. The right tool for this is `mypy --strict` (PY-012), not the linter.
- **`D` (pydocstyle)** — Requires docstrings everywhere. Heavy-handed; enable only if your project genuinely requires this discipline.
- **`COM` (commas)** — Argues with the formatter. Skip.
- **`DTZ` (flake8-datetimez)** — Flags naive `datetime` constructions (`datetime.now()`, `datetime.utcnow()`, naive `fromtimestamp`, etc.). Pairs directly with PY-073 (timezone-aware datetimes). Enable on projects that handle timestamps across system boundaries (databases, APIs, logs); it's noisy for pure-internal scripts where every datetime is constructed from a single source. Treat as opt-in per project, not part of the default set.
- **`TC` (flake8-type-checking, renamed from `TCH` in ruff 0.8)** — Moves type-only imports into `if TYPE_CHECKING:` blocks automatically (PY-014). Most useful on Python 3.14+ projects that don't carry `from __future__ import annotations`; when that future import *is* present it can produce false positives (ruff#15681). Considered opt-in, not part of the default set.

**When NOT to apply.** Existing projects with their own rule
selection — don't reset to the recommended list and create thousands
of new violations. Adopt incrementally: enable one new family at a
time, fix the violations, commit, move to the next.

---

## PY-022 — Per-file ignores for tests and `__init__.py`

**What.** Some rules are universally right *except* in specific
file patterns. Handle that with `per-file-ignores`, not global
`ignore`.

```toml
[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = [
  "S101",     # asserts are pytest's primary mechanism
  "S105",     # hardcoded "password" in test fixtures is OK
  "S106",     # same — test passwords
  "S107",     # same — test passwords
]
"__init__.py" = [
  "F401",     # re-exports look unused to Pyflakes
  "F403",     # `from .submodule import *` — sometimes needed
]
"src/legacy/**/*.py" = [
  "ALL",      # extreme: ignore everything in legacy modules
]
```

**Why.** The alternative — global `ignore = ["S101"]` — silences
the rule *everywhere*, including production code. A `assert
user.is_admin` in a request handler is a real security issue
because Python's `-O` flag strips asserts; you want that flagged
in production code, just not in tests.

Per-file ignores let you keep the rule strict where it matters and
relax it where it doesn't. Three common patterns:

1. **Tests use asserts as the test mechanism** → relax `S101` in `tests/`.
2. **`__init__.py` re-exports look unused** → relax `F401` only there.
3. **Legacy modules migrating in** → relax aggressively until they're cleaned up.

**How.** Use glob patterns matching ruff's path resolution
(relative to `pyproject.toml`):

```toml
[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["S101", "S105", "S106", "S107"]
"__init__.py" = ["F401", "F403"]
"src/mypackage/_generated.py" = ["E", "F"]       # ignore most of generated code
"scripts/**/*.py" = ["T201"]                      # print() is OK in scripts
"conftest.py" = ["F401", "F811"]                  # pytest fixtures
"docs/**/*.py" = ["ALL"]                          # doc snippets shouldn't lint
```

**When NOT to apply.** Don't reach for per-file ignores to hide
genuine issues — if every file in `src/mypackage/handlers/` needs
`S105` ignored, you have a real problem (hardcoded passwords in
production), not a per-file-ignore problem.

---

## PY-023 — Line length: 88 default

**What.** Line length is `88` (the ruff/black default). Set it
explicitly anyway:

```toml
[tool.ruff]
line-length = 88
```

**Why.** 88 is "Black's choice for a reason": 10% wider than
PEP 8's 79, which removes most of the gratuitous line-wrapping
pain, but narrow enough that side-by-side diffs in GitHub still
fit on a laptop screen. It's the de facto standard for new Python
projects in 2026.

Three failure modes from picking something else:

1. **79 (PEP 8's original)** — pre-dates modern editors. Forces ugly continuation patterns (`(\n    long_argument,\n    other_arg,\n)`) on lines that would fit fine in any IDE.
2. **120 (some teams' preference)** — fits more on a line, but GitHub PR view is ~100 chars before horizontal scroll. Reviewers stop seeing the right side of long lines.
3. **No setting** — ruff's default is 88, but if your team flips to a different formatter or someone overrides locally, the file diff becomes noisy.

**How.**

```toml
[tool.ruff]
line-length = 88              # set explicitly
target-version = "py311"

[tool.ruff.format]
quote-style = "double"        # ruff format default; "single" or "preserve" also valid
indent-style = "space"
docstring-code-format = true  # format code blocks inside docstrings (1.0+)
```

**When NOT to apply.** Three real cases:

1. **Established codebase already at 100 or 120.** Don't switch — the cost of reformatting every file outweighs the benefit. Consistency within a project beats any specific value.
2. **Data-heavy code.** Files with lots of pandas chains, SQL queries, or scientific computation legitimately go long. 100 or 120 is reasonable for those projects.
3. **Library that publishes a docstring style guide.** If your project documents 100-char as the standard, keep it.

For *new* projects without an existing constraint: 88.

---

## PY-024 — pre-commit hook order: `ruff` (--fix) before `ruff-format`

**What.** When configuring ruff in pre-commit, put `ruff-check` (the
linter) *before* `ruff-format` (the formatter):

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: 2eeb5678de71a00c0902cbda7105d328432f72cb  # frozen: v0.16.8
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format
```

**Why.** Lint fixes can produce output that needs reformatting:

- `--fix` may unwrap a multi-line function call after removing an unused argument.
- `--fix` may inline a one-line `if/else` that was previously multi-line.
- Import sorting (the `I` family) reorders imports, which can change blank-line patterns.

If `ruff-format` runs first, then `ruff --fix` modifies code, the
file is left in an unformatted state — committed, then the *next*
pre-commit run reformats it. You get noisy commits.

Running lint with `--fix` first, then format, produces a single
clean state per commit.

**How.**

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: 2eeb5678de71a00c0902cbda7105d328432f72cb  # frozen: v0.16.8
    hooks:
      - id: ruff-check
        name: ruff (lint + fix)
        args: [--fix, --exit-non-zero-on-fix]
      - id: ruff-format
        name: ruff (format)
```

`ruff-check` is the hook id the
[ruff-pre-commit README](https://github.com/astral-sh/ruff-pre-commit) uses
today. Pin `rev` to the full commit SHA with a `# frozen: vX.Y.Z` comment
(`pre-commit autoupdate --freeze` writes that form) so a moved tag can't
change what runs.

`--exit-non-zero-on-fix` makes pre-commit fail when ruff *does*
fix something — forcing you to re-stage the fixed file. Without it,
pre-commit succeeds and the fix is silently ungrouped from the
commit.

For projects without pre-commit, the same order in a Makefile:

```makefile
.PHONY: lint
lint:
	ruff check . --fix
	ruff format .
```

In CI, you typically want `--check` mode (fail without fixing):

```yaml
- run: uv run ruff check .
- run: uv run ruff format --check .
```

**When NOT to apply.** Single-step workflows where only one of
lint/format runs — no ordering issue. The rule applies when you
have both hooks active.

---

## PY-025 — Enable `RUF100` to flag unused `noqa` directives

**What.** `RUF100` errors on `# noqa: CODE` comments where the
referenced rule no longer fires on that line. Add it to your rule
selection:

```toml
[tool.ruff.lint]
select = [..., "RUF100"]
```

(It's included in the broader `RUF` family from PY-021's
recommended config, so if you selected `"RUF"`, you already have it.)

**Why.** Suppression comments are deadweight if not pruned:

1. **They mask future issues.** A bare `# noqa: F841` (unused variable) on a line that was refactored — and the variable now *is* used — still tells future readers "the linter complained here." When a real F841 appears later, reviewers ignore it because "we always have noqa around here."
2. **They obscure intent.** `# noqa: E501` on a line that fits within 88 chars now reads like "this rule used to fire but doesn't anymore" — and either the comment is wrong, or the linter config changed and nobody updated the comments. RUF100 forces you to either fix the comment or recognize it's dead.
3. **They accumulate.** Over a year, a codebase accumulates dozens of `# noqa` for code that was changed long ago. RUF100 catches them all.

**How.**

```toml
[tool.ruff.lint]
select = ["RUF100"]    # or include the whole RUF family
```

When RUF100 fires:

```python
import os  # noqa: F401  <-- RUF100: F401 doesn't apply here anymore
```

Either remove the suppression (the simple case) or update the code
(if the suppression was the only thing hiding a real issue).

`mypy` has the equivalent: `warn_unused_ignores = true` (part of
strict mode, PY-012) — flags `# type: ignore[code]` that no longer
suppresses anything.

**When NOT to apply.** Never. RUF100 is pure win. The only "false
positive" is when a suppression is genuinely needed but only on
some Python versions (e.g. an `S301` pickle suppression that only
fires on 3.13+) — in that case use `noqa: code  # version-specific`
with the version comment, and tolerate the false positive on the
non-matching version.

## PY-088 — Use ruff range suppression for multi-line blocks

**What.** Ruff 0.15+ supports block-level suppression:
`# ruff: disable[CODE]` opens a suppressed range and `# ruff: enable[CODE]`
closes it; `# ruff: file-ignore[CODE]` suppresses for a whole file. Use
it for generated-code sections, migration chunks, or embedded
third-party code where per-line `# noqa` would be noise.

**Why.** Scattering `# noqa: CODE` across 10+ consecutive lines is
visual clutter and easy to get inconsistent. A single
disable/enable pair brackets the block cleanly.

**How.**

```python
# ruff: disable[E501]
LONG_GENERATED_TABLE = [
    "................................................................ very long",
    "................................................................ very long",
]
# ruff: enable[E501]
```

Always name the rule code; never a bare `# ruff: disable`. Keep per-line
`# noqa: CODE` (PY-016) for targeted single-line suppressions — range
suppression is for blocks.

**When NOT to apply.** Single-line or single-statement suppressions —
those stay as `# noqa: CODE` (PY-016), which is more local and shows up
in `RUF100` unused-suppression checks (PY-025).

---

## PY-091 — Never `return` / `break` / `continue` out of a `finally` block

**What.** A `return`, `break`, or `continue` that exits a `finally`
block silently swallows any in-flight exception and discards the `try`
block's return value. Python 3.14 (PEP 765) emits a `SyntaxWarning` for
it; ruff's `B012` already flags it.

**Why.** This is a classic footgun: an exception propagating out of
`try` is *cancelled* the moment `finally` executes a `return`, so errors
vanish with no trace and the function returns a value the author didn't
intend. It almost always indicates a logic mistake, not a deliberate
choice.

**How.**

```python
# wrong — the return in finally eats any exception from do_work()
def f():
    try:
        return do_work()
    finally:
        return cleanup()        # B012 / SyntaxWarning

# right — let finally do cleanup only; return outside it
def f():
    try:
        return do_work()
    finally:
        cleanup()
```

Treat the 3.14 warning as an error in CI:
`filterwarnings = ["error::SyntaxWarning"]` in pytest, plus ruff `B012`.

**When NOT to apply.** None — there's no correct use. If you think you
need it, restructure so the control-flow statement lives outside the
`finally`.

---

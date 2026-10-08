---
type: gotcha
title: Multiple modules' pytest tests run in one session—conftest imports collide
description: pytest collects modules/*/test/ in one session, so from conftest import X resolves to the first conftest.py on sys.path; load shared data by path or put it in a sibling module instead.
tags: [testing, pytest, check-sh, modules]
generated: {by: okf-wiki/haiku, at: 2026-10-07T17:04:39Z}
verified:
  - {by: okf-wiki/haiku, at: 2026-10-07T17:04:39Z, commit: b4b436d878a1}
  - {by: okf-wiki/sonnet, at: 2026-10-08T17:17:08Z, commit: d81a0ab6df3d}
sources:
  - {resource: bin/check.sh, id: s1}
  - {resource: modules/artifacts/test/test_artifactctl.py, id: s2}
  - {resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/86, id: s3}
---

# Multiple modules' pytest tests run in one session—conftest imports collide

## Symptom

Tests pass when run alone (`pytest modules/artifacts/test`) but fail in CI or `bin/check.sh` with `ImportError: cannot import name 'X' from 'conftest'`. The error appears only when multiple modules' test directories are collected in the same pytest session.

## What fails

Using a plain Python import in a module's test to load conftest data [^s2]:
```python
from conftest import GOOD_PAGE
```

When `bin/check.sh` runs `pytest` on `modules/*/test/`, pytest loads every conftest.py as a plugin (for fixtures), but a plain import name resolves via sys.path to the **first directory** pytest examined, not necessarily the sibling conftest. If `modules/pr-flow/test/conftest.py` loads before `modules/artifacts/test/conftest.py`, the bare name resolves to the pr-flow conftest, which lacks `GOOD_PAGE`.

## What works

**Option 1: Load conftest by file path** [^s2]. Use `importlib.util.spec_from_file_location()` to load the sibling conftest explicitly:
```python
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("artifacts_conftest", Path(__file__).with_name("conftest.py"))
_conf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_conf)
GOOD_PAGE = _conf.GOOD_PAGE
```

**Option 2: Keep shared test data in a sibling module**. Create `_pages.py` or `_fixtures.py` next to conftest (not inside it), then `from _pages import GOOD_PAGE`. The leading underscore signals "internal sibling," and pytest won't treat it as a conftest collision.

## Why

`bin/check.sh` invokes pytest once, collecting all module tests in one session [^s1]:
```bash
uv run --with pytest … pytest -q modules/*/test
```

pytest loads each `conftest.py` file it finds as a plugin (to register fixtures), adding each directory to sys.path. A **plain `import conftest`** then resolves via sys.path's standard name-resolution—first match wins. Fixture discovery is by name binding within pytest's own plugin machinery, not by Python's import system, so the collision goes undetected until runtime when the test code tries to import.

## Verify

- `bin/check.sh` :: `pytest -q`
- `modules/artifacts/test/test_artifactctl.py` :: `spec_from_file_location`

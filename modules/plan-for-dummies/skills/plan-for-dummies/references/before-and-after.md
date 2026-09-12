# One task, written both ways

The task: add a per-user rate limit to the file-upload endpoint of a small FastAPI
service. The codebase already rate-limits one other endpoint. Both plans below were
written after the same investigation; only the writing differs.

## Before — the plan a strong model writes for itself, then over-corrects

```markdown
# Plan: Rate-limit uploads

## Context
The service exposes POST /upload in src/api/upload.py. Search is already rate-limited
via a decorator in src/ratelimit.py that reads a per-endpoint setting. We want the
same protection on uploads because a customer scripted 40k uploads last week.

## Environment and conventions
- Python 3.12, FastAPI 0.115, pydantic-settings 2.6 (see pyproject.toml). Settings
  live in src/settings.py as a pydantic BaseSettings subclass; env var names are
  the upper-cased field names.
- Tests are pytest; run `uv run pytest`. The suite takes ~40s and currently passes.
- Follow the existing pattern for decorators. Handle errors appropriately.

## Steps

### Step 1: Add the setting
Open src/settings.py. Around line 31 you will find the Settings class. Add a new
field for the upload limit, similar to search_rate_limit_per_min. Choose a sensible
default (10 is probably fine, but consider what the product team would want).

```python
class Settings(BaseSettings):
    search_rate_limit_per_min: int = 60
    upload_rate_limit_per_min: int = 10   # new
    ...
```

Check: `uv run python -c "from src.settings import Settings; print(Settings())"`
Expected: the new field appears.

### Step 2: Apply the decorator
Open src/api/upload.py. Find the upload handler (line ~18). Import rate_limited
from src.ratelimit and apply it the same way search does. Make sure the key you pass
matches the settings field. If the decorator needs the request object, wire it up
accordingly.

```python
from src.ratelimit import rate_limited

@router.post("/upload")
@rate_limited("upload_rate_limit_per_min")
async def upload_handler(request: Request, file: UploadFile) -> UploadResponse:
    ...  # existing body unchanged
```

Check: `uv run pytest tests/api/test_upload.py -q`
Expected: passes.

### Step 3: Add tests
Add tests mirroring tests/api/test_search.py::test_search_rate_limited. Cover the
happy path, the 429 path, and any edge cases you notice (concurrent requests,
limit of zero, etc.).

Check: `uv run pytest -q` → all pass.

## Success criteria
- Full suite passes.
- Uploads beyond the limit return 429.
- No other behaviour changes.

## Forbidden recovery moves
- Do not delete or skip failing tests.
- Do not add type: ignore.
- Do not use --no-verify.

## Report
Describe what you did for each step and paste test output.
```

What goes wrong with it, in the order the implementer meets it:

- "Around line 31" and "line ~18" drift the moment anything above them changes.
- "Choose a sensible default … consider what the product team would want" hands the
  implementer a product decision. So does "any edge cases you notice".
- "Handle errors appropriately", "wire it up accordingly", "similar to" are unmade
  decisions dressed as instructions.
- The pasted handler body is the one thing the implementer would have got right by
  reading the file, and now it is a second copy that can disagree with the real one.
- The decorator in this repo takes a *setting name string*. A plausible wrong move is
  passing the integer. Nothing in the plan says which, because the plan is busy
  restating things the implementer can read.
- The forbidden-moves block is the same in every plan this repo will ever get. It
  belongs in the implementer's standing instructions, once.
- Three per-step checks, two of which ("passes", "the new field appears") are
  descriptions, not outputs.

## After — the same task under this skill

```markdown
# Plan: Rate-limit POST /upload per user

## Goal
POST /upload returns 429 for a user who exceeds `upload_rate_limit_per_min`
requests in a minute. Search behaviour is unchanged.

## Read first
- `src/ratelimit.py` — `rate_limited`. It takes the *name of a Settings field* as a
  string and reads the limit at request time.
- `src/api/search.py` — `search_handler`, the only current use of `@rate_limited`.
- `tests/api/test_search.py` — `test_search_rate_limited`, the test shape to copy.

## Stop if
- `search_handler` is not decorated with `@rate_limited("search_rate_limit_per_min")`.

## Steps
1. Add `upload_rate_limit_per_min: int = 10` to `Settings` in `src/settings.py`,
   directly under `search_rate_limit_per_min`.
2. In `src/api/upload.py`, decorate `upload_handler` with
   `@rate_limited("upload_rate_limit_per_min")`, placed *below* `@router.post`.
   Watch out: the argument is the field name as a string, not the integer, and the
   decorator must be the inner one or FastAPI registers the unlimited function.
   Checkpoint: `uv run pytest tests/api/test_upload.py -q` → `3 passed`
3. Add `test_upload_rate_limited` to `tests/api/test_upload.py` by copying
   `test_search_rate_limited`, substituting the upload client call and the setting
   name. Assert the 11th call in a minute returns 429 and the 10th returns 200.
   Checkpoint: `uv run pytest tests/api/test_upload.py -q` → `4 passed`

## Done when
- `uv run pytest -q` → `212 passed`
- Only these files changed: `src/settings.py`, `src/api/upload.py`,
  `tests/api/test_upload.py`

## Report back
Files changed / commands run with pasted output / deviations / unsure about.
```

Same investigation, 28 lines instead of 70. Every decision is made (default 10,
decorator order, the string argument, which test to copy, what the test asserts).
Nothing is pasted that the implementer can read in the repo. The two things a
weaker model plausibly gets wrong each have one Watch-out line. The checkpoints are
real outputs from running the commands before writing them down. The reviewer's
rubric is the Done-when block and one `git diff --stat`.

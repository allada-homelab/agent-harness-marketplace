# pr-flow

Branch + worktree → PR → watch until green → (merge when told) → teardown.
One skill (`skills/pr-flow/SKILL.md`), one script beside it (`pr-flow.py`), one
PostToolUse hook that hints — never blocks — when a tracked file is edited on a
protected branch in a repo's main checkout.

Verbs: `start <slug>`, `open`, `watch [--merge]`, `teardown [branch]`, `gc`.
Exit codes: 0 green/merged/ok · 10 checks-failed · 11 conflict · 12 review ·
13 closed · 14 timeout · 15 attempts-exhausted · 2 refusal.
Tests: `uv run --with pytest --python 3.12 pytest -q modules/pr-flow/test`.

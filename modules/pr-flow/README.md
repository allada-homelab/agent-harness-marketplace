# pr-flow

Branch + worktree → PR → watch until green → (merge when told) → teardown.
One skill (`skills/pr-flow/SKILL.md`), one script beside it (`pr-flow.py`), one
PostToolUse hook that hints — never blocks — when a tracked file is edited on a
protected branch in a repo's main checkout.

Verbs: `start <slug> [--base <branch>] [--carry [<path>...]]`, `open`,
`watch [--merge]`, `teardown [branch]`, `gc`.
Exit codes: 0 green/merged/ok · 10 checks-failed · 11 conflict · 12 review ·
13 closed · 14 timeout · 15 attempts-exhausted · 2 refusal.

`start` refuses on a dirty main checkout by default — pass `--carry` to move
every uncommitted change into the new worktree, or `--carry <path>...` for
specific ones, so another session's edits are never swept up by accident. The
`--base` it was started with is recorded (`branch.<name>.pr-flow-base`) and
used by `open`, `watch`'s conflict hint, and `teardown`'s merged-into check, so
a worktree started off a non-default base stays consistent through the whole
flow. `watch` also reports `review` for a draft PR or one `mergeStateStatus:
BLOCKED` by branch protection, and its `--merge` binds to the head commit it
last polled green (`gh pr merge --match-head-commit`) — if the head moved
since, it refuses rather than merging a newer, unreviewed commit. An empty
`statusCheckRollup` (no CI configured, or the gap right after `open`'s push
before GitHub Actions registers its check runs) is polled for up to
`--no-checks-grace` seconds (default 300, reset whenever the head moves)
before `watch` treats it as green — a check that shows up during the grace
window is classified normally, failure included. Every poll also fetches
`origin/<branch>` and refuses to classify a snapshot whose `headRefOid` is not
the commit actually pushed: right after a push GitHub's PR object can still
report the previous head with its already-green checks, which used to come back
`green` in seconds for a commit whose CI had not started. That wait is bounded by
the same grace window; past it the snapshot is classified but `--merge` refuses,
as it does after an empty rollup. The post-merge confirmation read tolerates the
same lag (five reads, two seconds apart) before giving up.

Tests: `uv run --with pytest --python 3.12 pytest -q modules/pr-flow/test`.

# pr-flow

Branch + worktree → PR → watch until green → (merge when told) → teardown.
One skill (`skills/pr-flow/SKILL.md`), one script beside it (`pr-flow.py`), one
PostToolUse hook that hints — never blocks — when a tracked file is edited on a
protected branch in a repo's main checkout.

Verbs: `start <slug> [--base <branch>] [--carry [<path>...] | --leave-dirty]`, `open`,
`watch [--merge]`, `teardown [branch]`, `gc`. `teardown` and `gc` remove the
worktree and delete the branch locally **and on origin**, and only once it is
merged — an ancestor of `origin/<base>`, or a merged PR on GitHub (squash and
rebase merges). `open` from a fork clone owner-qualifies the head.
Exit codes: 0 green/merged/ok · 10 checks-failed · 11 conflict · 12 review ·
13 closed · 14 timeout · 15 attempts-exhausted · 2 refusal.

`start` refuses a local branch that already exists without a worktree, and if the
worktree cannot be created after a `--carry` it restores the carried work to main
before failing, so no stash entry is ever left behind. It refuses on a dirty main checkout by default — pass `--carry` to move
every uncommitted change into the new worktree, or `--carry <path>...` for
specific ones, or `--leave-dirty` to branch anyway and leave every one of them
on main — so another session's edits are never swept up by accident. `open`
refuses, before pushing, a branch with no commits ahead of its base (usually a
commit a pre-commit hook rejected). On Claude Code, `bin/pr-flow` puts a bare
`pr-flow` on the Bash `PATH` while the plugin is enabled; other harnesses run
`skills/pr-flow/pr-flow.py` with `python3`. The
`--base` it was started with is recorded (`branch.<name>.pr-flow-base`) and
used by `open`, `watch`'s conflict hint, and `teardown`'s merged-into check, so
a worktree started off a non-default base stays consistent through the whole
flow. `watch` also reports `review` for a draft PR or one `mergeStateStatus:
BLOCKED` by branch protection, and its `--merge` binds to the head commit it
last polled green (`gh pr merge --match-head-commit`) — if the head moved
since, it refuses rather than merging a newer, unreviewed commit; the same
refusal names gh's message and the other likely causes (merge commits disabled
— pr-flow only merges with a merge commit — or a branch-protection rule unmet).
A green head that is behind its base is reported with a hint, since "require
branches to be up to date" protection refuses such a merge. An empty
`statusCheckRollup` is either no CI for this PR (none configured, or every
workflow's `paths` filter misses the change) or the gap right after `open`'s
push before GitHub Actions registers its check runs. `watch` tells them apart
with `gh api repos/{owner}/{repo}/actions/runs?head_sha=`: a matching workflow
registers a run within seconds, so zero runs on a head whose
`mergeStateStatus` is `CLEAN`, held for `--no-runs-confirm` seconds (default
20), is a verified green that `--merge` acts on. Otherwise the empty rollup is
polled, at most every `--no-checks-poll` seconds (default 15, no backoff), for
up to `--no-checks-grace` seconds (default 300, reset whenever the head moves)
before `watch` treats it as an unverified green — a check that shows up during
the grace window is classified normally, failure included. Every poll also fetches
`origin/<branch>` and refuses to classify a snapshot whose `headRefOid` is not
the commit actually pushed: right after a push GitHub's PR object can still
report the previous head with its already-green checks, which used to come back
`green` in seconds for a commit whose CI had not started. That wait is bounded by
the same grace window; past it the snapshot is classified but `--merge` refuses,
as it does after an empty rollup. The post-merge confirmation read tolerates the
same lag (five reads, two seconds apart) before giving up.

Tests: `uv run --with pytest --python 3.12 pytest -q modules/pr-flow/test`.

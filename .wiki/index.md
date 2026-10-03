---
okf_version: "0.2"
---

# Gotcha

* [New skill descriptions cost pi tokens per request](./new-skill-costs-pi-tokens-per-turn.md) - Skill metadata is injected into every pi request; longer descriptions add recurring per-turn token cost that shipped unmeasured and must be audited in pin-bump PRs.
* [pr-flow merge closes PRs stacked on the merged branch](./pr-flow-merge-closes-stacked-prs.md) - pr-flow teardown (and watch --merge) push-deletes the branch on origin, and GitHub then closes every PR based on it; retarget stacked PRs to main before merging.
* [pr-flow watch crashes when its worktree is removed mid-poll](./pr-flow-watch-dies-if-worktree-removed.md) - pr-flow watch runs git and gh with the PR worktree as cwd; removing that worktree while a watch polls kills it with a traceback, which a piped exit code hides.

# Runbook

* [Removing a module](./removing-a-module.md) - Deleting modules/<name> leaves refs the gate misses — a stale root pi exclude, smoke tests naming it, lockfile importers — so sweep them; dated records get a note, not a rewrite.

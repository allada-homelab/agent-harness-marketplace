---
okf_version: "0.2"
---

# Gotcha

* [bin/check.sh fails on macOS without timeout binary](./check-sh-fails-on-macos-without-timeout.md) - bin/check.sh test suite fails on macOS hosts lacking timeout/gtimeout, though the fallback path passes; check assumes timeout exists to assert the fallback is reachable.
* [Chrome's IsolateSandboxedIframes silences deferred errors in headless probes](./chrome-isolates-sandboxed-iframes-from-virtual-time.md) - Chrome's sandboxed iframe isolation (`IsolateSandboxedIframes`) blocks `--virtual-time-budget`, silencing deferred errors; fix with `--disable-features=IsolateSandboxedIframes`.
* [Multiple modules' pytest tests run in one session—conftest imports collide](./module-tests-share-one-pytest-session.md) - pytest collects modules/*/test/ in one session, so from conftest import X resolves to the first conftest.py on sys.path; load shared data by path or put it in a sibling module instead.
* [New skill descriptions cost pi tokens per request](./new-skill-costs-pi-tokens-per-turn.md) - Skill metadata is injected into every pi request; longer descriptions add recurring per-turn token cost that shipped unmeasured and must be audited in pin-bump PRs.
* [pr-flow merge closes PRs stacked on the merged branch](./pr-flow-merge-closes-stacked-prs.md) - pr-flow teardown (and watch --merge) push-deletes the branch on origin, and GitHub then closes every PR based on it; retarget stacked PRs to main before merging.
* [pr-flow watch crashes when its worktree is removed mid-poll](./pr-flow-watch-dies-if-worktree-removed.md) - pr-flow watch runs git and gh with the PR worktree as cwd; removing that worktree while a watch polls kills it with a traceback, which a piped exit code hides.
* [pr-flow watch false-green on delayed CI](./pr-flow-watch-false-green-on-delayed-ci.md) - pr-flow watch can report false green when GitHub delays CI startup; zero runs means 'not started yet', not 'no CI applies' — confirm with gh run list

# Runbook

* [Removing a module](./removing-a-module.md) - Deleting modules/<name> leaves refs the gate misses — a stale root pi exclude, smoke tests naming it, lockfile importers — so sweep them; dated records get a note, not a rewrite.

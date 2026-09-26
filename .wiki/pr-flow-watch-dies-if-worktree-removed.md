---
type: gotcha
title: pr-flow watch crashes when its worktree is removed mid-poll
description: pr-flow watch runs git and gh with the PR worktree as cwd; removing that worktree while a watch polls kills it with a traceback, which a piped exit code hides.
tags: [pr-flow, watch, worktree, exit-code]
generated: {by: okf-wiki/opus, at: 2026-09-26T14:22:38Z}
verified:
  - {by: okf-wiki/opus, at: 2026-09-26T14:22:38Z, commit: 6ac844bcd7e8}
sources:
  - {id: s1, resource: modules/pr-flow/skills/pr-flow/pr-flow.py, title: sh() passes cwd to subprocess.run; cmd_watch catches only Fail and TimeoutExpired}
  - {id: s2, resource: "session report 2026-09-16, BetterPostgresCheckpointer #135 during the python-template v0.25.0 rollout", title: watch died silently after a manual worktree remove}
---

# pr-flow watch crashes when its worktree is removed mid-poll

## Symptom

A background `pr-flow watch ... | tail` ends with exit 0 but never printed its
`pr-flow: watch <verdict> <url>` line. The real output is a Python traceback ending
in `FileNotFoundError` for the worktree path.[^s2]

## What fails

`cmd_watch` takes `Path.cwd()` (the PR worktree) and every poll runs `gh pr view`,
`git fetch` and friends through `sh()`, which hands that path to `subprocess.run` as
`cwd`. Once the directory is gone, `subprocess.run` raises `FileNotFoundError`
before any child starts; the poll loop catches only `Fail` and `TimeoutExpired`, and
`main()` catches only `Fail`, so the process dies with exit 1.[^s1] Piped through
`tail`/`head`, the pipeline's status is the last command's 0, so the crash reads as
a clean run — and a red CI goes unreported.

## What works

- Remove a PR worktree (by hand, `pr-flow teardown` or `gc` from another shell) only
  after that watch printed its verdict line. `watch --merge` tearing down its own
  worktree is safe: it chdirs to the main checkout first.
- Judge a watch by its `pr-flow: watch <verdict>` line, never by an exit code that
  came through a pipe; if unsure, re-check with `gh pr checks <n>`.

## Why

Polling from the worktree is how watch resolves the branch, the repo and the pushed
head (`repo_ctx(cwd)`, `pushed_head(cwd, branch)`); nothing re-validates the cwd
between polls. A fix would catch `OSError` in the poll loop and refuse with a
`pr-flow:` line.

## Verify

- `modules/pr-flow/skills/pr-flow/pr-flow.py` :: `p = subprocess.run([str(a) for a in args], cwd=cwd, text=True, capture_output=True, timeout=timeout)`
- `modules/pr-flow/skills/pr-flow/pr-flow.py` :: `except (Fail, subprocess.TimeoutExpired) as e:`
- `modules/pr-flow/skills/pr-flow/pr-flow.py` :: `os.chdir(ctx.main_root)  # never end as a process whose cwd was just removed`
- `modules/pr-flow/skills/pr-flow/pr-flow.py` :: /except \(Fail, subprocess\.TimeoutExpired, OSError\)/ => 0

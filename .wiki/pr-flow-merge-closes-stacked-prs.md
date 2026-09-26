---
type: gotcha
title: pr-flow merge closes PRs stacked on the merged branch
description: pr-flow teardown (and watch --merge) push-deletes the branch on origin, and GitHub then closes every PR based on it; retarget stacked PRs to main before merging.
tags: [pr-flow, github, stacked-prs, teardown]
generated: {by: okf-wiki/opus, at: 2026-09-26T14:22:38Z}
verified:
  - {by: okf-wiki/opus, at: 2026-09-26T14:22:38Z, commit: 6ac844bcd7e8}
sources:
  - {id: s1, resource: modules/pr-flow/skills/pr-flow/pr-flow.py, title: teardown runs git push origin --delete}
  - {id: s2, resource: https://github.com/allada-homelab/python-template/pull/88, title: stacked PR closed when its base feat/sha-pin-actions was merged and deleted}
  - {id: s3, resource: https://github.com/allada-homelab/python-template/pull/91, title: the same change reopened against main}
---

# pr-flow merge closes PRs stacked on the merged branch

## Symptom

After `pr-flow watch --merge` (or `pr-flow teardown`) on a PR that other PRs were
stacked on (`pr-flow start --base <that-branch>`), those PRs show `CLOSED`, not
retargeted to `main`. Nothing prints a warning; you find out from `gh pr view`.[^s2]

## What fails

Teardown ends with `git push origin --delete <branch>`.[^s1] GitHub closes every open
PR whose base is a branch deleted that way; the closed PR was not recoverable in
place and had to be reopened as a new one. Seen 2026-09-23: python-template #88 (base
`feat/sha-pin-actions`) closed when that base merged, and came back as #91 on
`main`.[^s2][^s3]

## What works

Before merging a branch that has PRs stacked on it, for each stacked PR:

1. `gh pr edit <n> --base main`
2. `git config branch.<stacked-branch>.pr-flow-base main` in the main checkout, so
   pr-flow's recorded base follows (it reads `branch.<name>.pr-flow-base`).

Already closed: in the stacked worktree `git merge origin/main`, push, then
`pr-flow open` to open a fresh PR.

## Why

pr-flow deletes the remote branch on purpose, so merged branches do not pile up;
the SKILL documents the deletion but not its effect on PRs stacked on top. This is
GitHub behavior, not a pr-flow bug, so a change to pr-flow's teardown (for example
leaving the remote branch alone when a PR targets it) is the only code-side fix.

## Verify

- `modules/pr-flow/skills/pr-flow/pr-flow.py` :: `"push", "-q", "origin", "--delete", branch`
- `modules/pr-flow/skills/pr-flow/pr-flow.py` :: `pr-flow-base`
- `modules/pr-flow/skills/pr-flow/SKILL.md` :: /[Ss]tacked/ => 0

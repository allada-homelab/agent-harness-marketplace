---
type: decision
title: Repo-sweep ledger lives outside the checkout; sync clears the unit queue
description: repo-sweep ledger is a sqlite file under $XDG_STATE_HOME, not the repo, so parallel fix PRs never conflict; never run sync between a fixer finishing and repo-sweep pr, it drops the unit.
tags: [sqlite, worktree]
generated: {by: okf-wiki/unknown, at: 2026-11-18T15:14:17Z}
verified:
  - {by: okf-wiki/unknown, at: 2026-11-18T15:14:17Z, commit: db3402ed2a83}
sources:
  - {resource: modules/repo-sweep/skills/repo-sweep/repo_sweep.py, id: s1}
  - {resource: modules/repo-sweep/README.md, id: s2}
  - {resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/202, id: s3}
---

# Repo-sweep ledger lives outside the checkout; sync clears the unit queue

## Decision

The repo-sweep findings ledger is one sqlite database per repository, stored under `$XDG_STATE_HOME/repo-sweep/` (or `REPO_SWEEP_HOME`), outside the checkout [^s1] [^s2]. Clones and worktrees of one origin share it, because the key is derived from the origin URL [^s1].

## Why

A committed ledger would make every `repo-sweep-fix` pull request flip statuses in the same file, so parallel fix PRs would conflict [^s3]. The read-only find mode also must not dirty the working tree [^s3]. A committed copy is available with `repo-sweep report --out <dir>` [^s3].

## Rejected alternatives

A committed JSONL or Markdown ledger in the repo: rejected for the conflicts above [^s3].

## Revisit when

The fix runs stop being parallel, or the ledger needs review in PRs.

## Rule that bites

`sync` (and `plan`, which calls it) runs `DELETE FROM units` [^s1]: the queue belongs to one run, while findings persist [^s1]. Running `sync` after a fixer finished but before `repo-sweep pr <unit> <url>` removes the finished unit. `pr` then fails with "not a finished fix unit", the findings stay `confirmed`, and the next fix run opens a duplicate pull request [^s3].

## Verify

- `modules/repo-sweep/skills/repo-sweep/repo_sweep.py` :: `def locate`
- `modules/repo-sweep/skills/repo-sweep/repo_sweep.py` :: `DELETE FROM units`
- `modules/repo-sweep/README.md` :: `## The ledger`

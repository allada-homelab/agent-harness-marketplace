---
type: gotcha
title: Parallel pr-flow starts in one repo fail on git locks — start now flocks a lock
description: Parallel pr-flow start in one repo races git's no-retry locks (.git/config, commit-graph-chain.lock under fetch.writeCommitGraph); cmd_start now flocks pr-flow-start.lock in common_dir.
tags: [pr-flow, worktree]
generated: {by: okf-wiki/deepseek, at: 2026-11-10T14:08:30Z}
verified:
  - {by: okf-wiki/deepseek, at: 2026-11-10T14:08:30Z, commit: eab0f90a0c28}
sources:
  - {id: s1, resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/167, title: "pr-flow 0.2.20: serialize start so parallel worktree creation can't fail"}
---

# Parallel pr-flow starts in one repo fail on git locks — start now flocks a lock

## Symptom

Two `pr-flow start` runs in the same repo — a workflow's isolated agents each starting at once — race and one dies with a git lock error: `.git/config.lock` from the base/tracking writes, or `commit-graph-chain.lock` when a fetch writes the commit graph under `fetch.writeCommitGraph`.[^s1]

## What fails

`cmd_start` writes `.git/config` (tracking fetch, `branch.<b>.pr-flow-base`) and fetches, and with `fetch.writeCommitGraph` a fetch also writes the commit-graph chain. Git takes these locks with no retry, so two starts in one repo cannot both win; the loser fails before its worktree exists.

## What works

- `cmd_start` opens `<common_dir>/pr-flow-start.lock` and holds `fcntl.flock(..., LOCK_EX)` until exit — one start per repo; a concurrent start blocks instead of failing.
- A workflow that spawns isolated agents can still run starts concurrently; the lock serializes them, so no coordination is needed beyond starting them in the same checkout.

## Why

Git's config and commit-graph locks are no-retry and the two starts' critical sections overlap in the same repo. Serializing inside `start` with a lock file is the only fix that works without changing git config or adding cross-agent coordination.

## Verify

- `modules/pr-flow/skills/pr-flow/pr-flow.py` :: `fcntl.flock(lock, fcntl.LOCK_EX)`

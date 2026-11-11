---
type: gotcha
title: pr-flow teardown runs devc down before removing the worktree
description: Agent worktree dev containers, images and per-worktree volumes leak after git worktree remove; pr-flow teardown now runs devc down first (PR_FLOW_DEVC overrides the binary).
tags: [pr-flow, teardown, worktree]
generated: {by: okf-wiki/deepseek, at: 2026-11-10T14:09:42Z}
verified:
  - {by: okf-wiki/deepseek, at: 2026-11-10T14:09:42Z, commit: eab0f90a0c28}
sources:
  - {id: s1, resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/71, title: "pr-flow: run devc down during teardown (0.2.8)"}
---

# pr-flow teardown runs devc down before removing the worktree

## Symptom

After `pr-flow teardown`, the worktree is gone but its dev container, image and per-worktree volumes stay behind. Nothing else in the chain — devcontainer CLI, git, the harness — removes them once the worktree is gone, so disk fills over time.[^s1]

## What fails

Each agent worktree usually gets its own dev container with per-worktree volumes. `git worktree remove` only deletes the checkout; the container, image and volumes are Docker objects keyed off the worktree path and are not reclaimed by any later step.

## What works

- `teardown` calls `devc_down(wt)` before `git worktree remove --force` when a `devc` executable is on PATH.[^s1]
- `devc_down` runs `devc down <worktree>` in its own session (so a timeout kills devc's docker children too), with `PR_FLOW_DEVC_TIMEOUT` (default 300s) bounding the wait.
- Best effort: a missing devc, a timeout or a non-zero rc is a warning and teardown continues; it never blocks removing the worktree or deleting the branch.
- `PR_FLOW_DEVC` overrides the binary name, like `PR_FLOW_GH`/`PR_FLOW_GIT`; tests set it to a missing name so they never reach a real docker daemon.
- `pr-flow gc` reuses the same teardown path, so stale merged worktrees get their containers reclaimed too.

## Why

The devcontainer CLI has no working `down` in the chain after the worktree is gone, so the reclaim belongs to teardown itself — but it must stay best-effort, because a wedged docker daemon must not turn a merged verdict into a failed teardown.

## Verify

- `modules/pr-flow/skills/pr-flow/pr-flow.py` :: /devc_down\(wt\)\s+git\("worktree", "remove"/ => 1

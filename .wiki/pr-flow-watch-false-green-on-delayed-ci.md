---
type: gotcha
title: pr-flow watch false-green on delayed CI
description: pr-flow watch can report false green when GitHub delays CI startup; zero runs means 'not started yet', not 'no CI applies' — confirm with gh run list
tags: [pr-flow, watch, ci, github-actions, delayed]
generated: {by: okf-wiki/haiku, at: 2026-10-05T15:44:10Z}
verified:
  - {by: okf-wiki/haiku, at: 2026-10-05T15:44:10Z, commit: 362cf7244be5}
sources:
  - {id: s1, resource: .github/workflows/ci.yml, title: pull_request trigger with no paths filter means all PRs invoke CI}
  - {id: s2, resource: PR https://github.com/allada-homelab/agent-harness-marketplace/pull/81 (2026-10-05), title: watch reported 'no CI applies' green after 35s while pull_request run appeared ~10 min later}
---

# pr-flow watch false-green on delayed CI

## Symptom

Right after `pr-flow open`, `pr-flow watch` printed `no workflow run exists for this head after 35s and GitHub reports it mergeable; no CI applies to this PR, treating as green`, then `pr-flow: watch green <url>`, exit 0. githubstatus showed Actions operational. The pull_request run (check + smoke) appeared roughly 10 minutes later and passed.[^s2]

## What fails

When a PR has no checks and GitHub finds no Actions run for its head, watch waits `--no-runs-confirm` seconds (default 20) and then calls it a *verified* no-CI green, which `--merge` treats as mergeable. In this repo that verdict is never correct: `.github/workflows/ci.yml` runs on every `pull_request` with no paths filter.[^s1] Zero runs here only means GitHub has not dispatched the run yet, so `--merge` on a fresh PR can merge with no CI at all.

## What works

- **Treat a no-CI green here as "not started":** confirm with `gh run list --branch <branch>` / `gh pr checks <n>` before reporting green or merging.
- **Raise the confirmation wait:** `pr-flow watch --no-runs-confirm <seconds>` holds longer before concluding no CI applies.
- **Kick CI explicitly:** `gh workflow run ci.yml --ref <branch>` starts a run on the head; once checks show up, a fresh `pr-flow watch --merge` waits for them and merges on real green (what PR #81 did).[^s2]

## Why

GitHub dispatches `pull_request` and `push` workflow runs asynchronously, and the dispatch delay can be minutes even with no reported incident. The merge's `push` run on main, which cuts the release tag, was delayed the same way that day. pr-flow's no-runs heuristic suits repos whose workflows are paths-filtered, but this repo's CI has no filter.[^s1]

## Verify

- `.github/workflows/ci.yml` :: `pull_request`

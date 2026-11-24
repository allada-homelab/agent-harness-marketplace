---
type: gotcha
title: pr-flow watch false-green on delayed CI
description: Before 0.2.22 pr-flow watch called zero Actions runs 'no CI applies' and --merge merged early; 0.2.22 skips that shortcut when a workflow runs on every PR
tags: [pr-flow, watch, ci, github-actions, delayed]
generated: {by: okf-wiki/haiku, at: 2026-10-05T15:44:10Z}
verified:
  - {by: okf-wiki/haiku, at: 2026-10-05T15:44:10Z, commit: 362cf7244be5}
  - {by: okf-wiki/opus, at: 2026-11-11T13:35:37Z, commit: be1798bb4cf1}
sources:
  - {id: s1, resource: .github/workflows/ci.yml, title: pull_request trigger with no paths filter means all PRs invoke CI}
  - {id: s2, resource: PR https://github.com/allada-homelab/agent-harness-marketplace/pull/81 (2026-10-05), title: watch reported 'no CI applies' green after 35s while pull_request run appeared ~10 min later}
  - {id: s3, resource: maintainer dotfiles PRs 661 and 662 (private repo; 2026-11-10), title: watch --merge merged before CI ran and PR 662 never got a pull_request run}
---

# pr-flow watch false-green on delayed CI

## Symptom

Right after `pr-flow open`, `pr-flow watch` printed `no workflow run exists for this head after 35s and GitHub reports it mergeable; no CI applies to this PR, treating as green`, then `pr-flow: watch green <url>`, exit 0. githubstatus showed Actions operational. The pull_request run (check + smoke) appeared roughly 10 minutes later and passed.[^s2]

## What fails

Before pr-flow 0.2.22, when a PR had no checks and GitHub found no Actions run for its head, watch waited `--no-runs-confirm` seconds (default 20) and then called it a *verified* no-CI green, which `--merge` acted on. In a repo whose workflow runs on every `pull_request` with no paths filter[^s1] that verdict is never correct: zero runs only means GitHub has not dispatched the run yet. It merged a dotfiles PR before its CI ran on 2026-11-10, and called the next one green while GitHub never fired its `pull_request` event at all.[^s3]

## What works

- **Fixed in pr-flow 0.2.22:** watch reads `.github/workflows/` first; if any workflow runs on every pull request, it skips the no-runs shortcut, waits out `--no-checks-grace`, and `--merge` refuses the unverified green.
- **On an older pin, or when the event never fires:** confirm with `gh pr checks <n>` before merging, and start CI with `gh workflow run <workflow> --ref <branch>`; once checks show up, a fresh `pr-flow watch --merge` merges on real green.[^s2]

## Why

GitHub dispatches `pull_request` and `push` workflow runs asynchronously, and the dispatch delay can be minutes even with no reported incident. The merge's `push` run on main, which cuts the release tag, was delayed the same way that day. pr-flow's no-runs heuristic suits repos whose workflows are paths-filtered, but this repo's CI has no filter.[^s1]

## Verify

- `.github/workflows/ci.yml` :: `pull_request`
- `modules/pr-flow/skills/pr-flow/pr-flow.py` :: `def unfiltered_pr_workflow`

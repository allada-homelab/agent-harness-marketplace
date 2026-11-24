---
type: gotcha
title: pr-flow watch counts a superseded CANCELLED run as a failure
description: pr-flow watch exits checks-failed on a CANCELLED check that a workflow concurrency group superseded; live_checks drops a CANCELLED run when a later run of the same workflow job exists.
tags: [pr-flow, watch, github-actions]
generated: {by: okf-wiki/deepseek, at: 2026-11-10T14:09:06Z}
verified:
  - {by: okf-wiki/deepseek, at: 2026-11-10T14:09:06Z, commit: eab0f90a0c28}
sources:
  - {id: s1, resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/155, title: "pr-flow: ignore cancelled check runs a later run replaced"}
---

# pr-flow watch counts a superseded CANCELLED run as a failure

## Symptom

`pr-flow watch` exits `checks-failed` (rc 10) on a PR whose jobs all passed — the rollup holds a CANCELLED run followed by a SUCCESS run of the same workflow job. Seen on a lumos PR where every ai-agents job had a CANCELLED run and a later SUCCESS run for the same head.[^s1]

## What fails

`CANCELLED` is in `BAD`, so any cancelled check in `statusCheckRollup` trips `checks-failed`. A workflow concurrency group that cancels a duplicate trigger leaves both runs side by side in the rollup for the same head; the cancelled one says nothing about the commit — only its replacement does — so counting it as a failure is a false red.

## What works

- `live_checks(pr)` returns `statusCheckRollup` minus each CANCELLED run that a later run of the same workflow job replaced — same `workflowName` and check name, compared by run id parsed from `detailsUrl` (`/actions/runs/<id>`).[^s1]
- `classify` and `print_failed_logs` both read `live_checks`, so the filter applies to the verdict and to the failed-log dump.
- When the cancelled run is still the only entry (the rerun's jobs have not reached the rollup yet), `classify` checks the Actions API via `newest_runs` and excludes a cancelled run a newer workflow run has replaced; a cancelled run with no later run still fails the watch.

## Why

GitHub's rollup keeps both the cancelled and the replacement run. A CANCELLED check is a real failure only when it is the latest run of its workflow job; otherwise the verdict belongs to the newer run.

## Verify

- `modules/pr-flow/skills/pr-flow/pr-flow.py` :: `def live_checks(pr):`

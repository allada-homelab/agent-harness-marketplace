---
type: gotcha
title: claude plugin eval refuses Bash grants when ~/.ssh holds a symlink
description: "`claude plugin eval` error about the SSH credential store holding a symlink: Bash-granting cases score 0.00 before the model runs, so verify local-workers routing with claude -p instead."
tags: [evals, claude-p, pi]
generated: {by: okf-wiki/scribe, at: 2026-11-15T16:59:34Z}
verified:
  - {by: okf-wiki/scribe, at: 2026-11-15T16:59:34Z, commit: 1cefeee9cdf3}
sources:
  - {id: session-2026-11-15, resource: "local run 2026-11-15 on David's workstation: claude plugin eval . --case control-no-local-request --trust-plugin --mocks off --allow-tools ... Bash --scaffold, from modules/local-workers"}
  - {id: eval-case, resource: "modules/local-workers/evals/generic-local-optin/prompt.md :: allowed_tools"}
---

# claude plugin eval refuses Bash grants when ~/.ssh holds a symlink

## Symptom

`claude plugin eval` reports `score 0.00`, `$0.00`, and the error "the SSH (~/.ssh) credential store on this machine holds a symbolic link inside it … a Bash-granting evaluation cannot run here". Every run errors before the model starts.

## What fails

Any case that grants `Bash` (for example `generic-local-optin`, whose `allowed_tools` includes `Bash`) on a host where `~/.ssh` contains a symlink. That covers every local-workers routing eval, since they all exercise `pi-run` through Bash.

## What works

Route-check the plugin with `claude -p` in a scratch directory:

`claude -p --plugin-dir modules/local-workers --output-format stream-json --verbose`

Read the `Skill` and `Bash` `tool_use` events. A correct run shows `Skill local-workers:delegate`, then `pi-run --read-only` Bash calls.

## Why

The error text says the credential store must be one plain directory; its root may itself be a link. Do not change `~/.ssh` to get the eval running. Accept the `claude -p` fallback instead.

## Verify

- `modules/local-workers/evals/generic-local-optin/prompt.md` :: `allowed_tools: [Read, Glob, Grep, Skill, Bash]`

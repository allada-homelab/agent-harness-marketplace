---
type: runbook
title: Run a module skill on pi without installing the package
description: pi -p --skill <checkout>/modules/<m>/skills/<s> runs a module skill on real pi without pi install; delegate_agent is absent there, so agents take the inline fallback.
tags: [pi, skills, modules, smoke, testing]
generated: {by: okf-wiki/haiku, at: 2026-11-04T15:39:43Z}
verified:
  - {by: okf-wiki/haiku, at: 2026-11-04T15:39:43Z, commit: 02f90b24e011}
sources:
  - {id: s1, resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/156, title: "PR #156 simplify skill: pi run verified 2026-11-04"}
  - {id: s2, resource: tests/smoke/pi.sh, title: smoke script installs the package with pi install}
  - {id: s3, resource: tests/smoke/dsh.sh, title: dsh smoke exercises only plan-for-dummies}
---

# Run a module skill on pi without installing the package

## When

You want to see a new or changed module skill work on real pi before the package
is installed or tagged. `pi install` writes `~/.pi` settings; `--skill` does not.[^s1]

## Steps

1. Make a scratch git repo with the planted files the skill should act on.
2. From that repo, run `pi -p --no-session --skill <checkout>/modules/<m>/skills/<skill> "/skill:<skill>"`.
   `pi --help` lists `--skill <path>  Load a skill file or directory`.[^s1]

## Check it worked

- Exit code 0, the skill resolves its target, and it edits or reports on the scratch repo.[^s1]
- Expect the agent to report that it found no delegation tool (the wording is the
  model's, not a fixed pi message): `delegate_agent` is absent in this run, so agent
  dispatch takes the skill's inline fallback.[^s1]
- This does not prove the skill loads on dsh. `tests/smoke/dsh.sh` only exercises
  plan-for-dummies,[^s3] so a new module's skill needs its own check there. The PROBE
  line in `tests/smoke/pi.sh` lists every loaded skill.[^s2]

## Verify

- `tests/smoke/pi.sh` :: `pi install "$repo"`

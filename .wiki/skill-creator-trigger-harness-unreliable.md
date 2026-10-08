---
type: gotcha
title: skill-creator trigger harness is unreliable for measuring descriptions
description: skill-creator's run_eval.py pollutes ~/.claude/commands and under-detects triggering (0-33% vs 12/12 independently), so run it from a scratch dir and measure with claude -p stream-json.
tags: [skills, evals, skill-creator, claude-p]
generated: {by: okf-wiki/sonnet, at: 2026-10-08T05:13:12Z}
verified:
  - {by: okf-wiki/sonnet, at: 2026-10-08T05:13:12Z, commit: edd5fec2d9b9}
sources:
  - {resource: modules/ste-writing/README.md, id: readme}
---

# skill-creator trigger harness is unreliable for measuring descriptions

## Symptom

Scoring a skill description with the official skill-creator plugin's `scripts/run_eval.py` (`python3 -m scripts.run_eval`) leaves `<skill>-skill-<id>.md` files in the global `~/.claude/commands/`. It also reports 0-33% triggering on explicit asks that an independent check triggered 12/12 [^readme].

## What fails

Run from the plugin directory, `find_project_root()` walks up to `~/.claude`, so the temp command files land in the global commands dir. Observed 2026-10-08 on Claude Code 2.1.293, skill-creator d4226d062928, while writing modules/ste-writing: six `ste-writing-skill-*.md` files, removed by hand.

Three runs (60 s and 180 s timeouts, Sonnet, 3 runs per query) scored 1/9, 0/9 and 0/9 should-trigger queries; all 11 should-not-trigger queries stayed at 0. The default 60 s timeout is also clipped by the fleet's full plugin load on every `claude -p` start. A `/ste-writing <text>` query can never pass, because the harness registers the skill under a randomized `<name>-skill-<id>` command name.

## What works

Run the harness from a scratch directory that holds its own `.claude/`, with `PYTHONPATH=<skill-creator skill dir>`. Use it only for the negative side.

Measure triggering yourself: `claude -p <query> --output-format stream-json --verbose` with `CLAUDECODE` unset in the env. Count a `Skill` tool_use whose input names the skill. This loop (file-free, inline text) gave 12/12 on four explicit queries and 0/6 on two near-miss negatives.

## Why

Cause of the under-detection is not established (inferred: the harness's detection of the skill call or its command registration). The independent stream-json count is the figure recorded in the module README.

## Verify

- `modules/ste-writing/README.md` :: `Triggering`

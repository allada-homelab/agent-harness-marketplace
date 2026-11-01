---
type: gotcha
title: annotate() resets parser-set injected flags on non-system rows
description: annotate() in transcripts.py clears injected on every non-system row outside its target set; keep harness-injected turns as role=system or the flag is wiped.
tags: [sqlite, injection]
generated: {by: okf-wiki/claude-haiku-5-5, at: 2026-11-01T14:44:38Z}
verified:
  - {by: okf-wiki/claude-haiku-5-5, at: 2026-11-01T14:44:38Z, commit: bae30dea28b6}
sources:
  - {id: test-guard, resource: "modules/agent-transcripts/test/test_ingest.py :: test_injected_claude_turns_stay_injected_after_annotate"}
  - {id: session-2026-11-01, resource: "local work 2026-11-01 on fix-transcripts-native-author-and-coverage: harness-injected Claude and dsh user turns"}
---

# annotate() resets parser-set injected flags on non-system rows

## Symptom

Harness-injected user turns (Claude `isMeta`, `isCompactSummary`, `origin.kind`; dsh `source.kind`) are marked `injected = 1` by the parser, then come back as `injected = 0` after `transcripts.py annotate` runs [^session-2026-11-01].

## What fails

`annotate()` recomputes the flag from scratch. Its statement `UPDATE messages SET injected = 0 WHERE injected = 1 AND id NOT IN (annotate_target)` clears every row that is neither a cross-session repeat nor `role = 'system'` [^session-2026-11-01].

## What works

The parser writes harness-injected turns as `role = 'system'`. `annotate_target` includes every `system` row, so the reset cannot touch them. `test_injected_claude_turns_stay_injected_after_annotate` guards this [^test-guard].

## Why

`annotate()` recomputes from `norm_key` and `role` on every run. A parser-set `injected` flag on a `user` row is not in its target set, so the next run clears it.

## Verify

- `modules/agent-transcripts/skills/transcript-ingest/transcripts.py` :: `annotate`

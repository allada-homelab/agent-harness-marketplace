---
type: gotcha
title: dsh session.v4 tool results carry the result at message level
description: dsh session.v4 tool/result rows hold the result on the message itself, so a v3-only parser stores empty text and no call link; read the message-level form too.
tags: [dsh]
generated: {by: okf-wiki/claude-haiku-5-5, at: 2026-10-31T23:36:00Z}
verified:
  - {by: okf-wiki/claude-haiku-5-5, at: 2026-10-31T23:36:00Z, commit: c755d6570ebb}
sources:
  - {resource: modules/agent-transcripts/skills/transcript-ingest/transcripts.py, id: s1}
  - {resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/139, id: s2}
---

# dsh session.v4 tool results carry the result at message level

## Symptom

A real-corpus rebuild of the transcript index showed every v4 tool result with empty text and no
result link, so tool-error sweeps reported zero v4 errors.[^s1]

## What fails

A parser that reads only v3's nested form (`data.message.content` blocks of type `tool-result` or
`toolResult`) finds nothing in a v4 row. All 33,494 v4 results in the validation run stored `text=''`,
and `tool_calls` had no `result_message_id` or `is_error`.[^s1]

## What works

Treat a `tool/result` row with no nested blocks but a `toolCallId` on the message as one result.
Agent-transcripts 0.9.5 does this in `parse_dsh`, and its test fixture runs over both shapes.[^s2]

## Why

v4 changed the shape. `data.message` is the result itself: `{id, role:"tool", toolCallId, isError,
source:{kind,callId}, content:[{type:"text",text}]}`. A row-level `data.error` still marks failures.
v3 nests `[{type:"tool-result", toolCallId, isError, content:[...]}]` under `data.message.content`.[^s1]

Lesson: when dsh bumps `session.vN`, check the tool/result shape, not only message counts. The
v3/v4 superset check (count plus first and last message) passed while all result text was missing.

## Verify

- `modules/agent-transcripts/skills/transcript-ingest/transcripts.py` :: `def parse_dsh`

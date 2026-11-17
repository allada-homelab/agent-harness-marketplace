---
type: gotcha
title: Compaction summaries quote earlier prompts; substring dedupe drops real ones
description: parse_claude drops a queued prompt only when the next human turn repeats it, start or end; substring hits compaction summaries, and any turn lets an earlier "go" swallow later ones.
tags: [injection]
generated: {by: okf-wiki/claude-haiku-5-5, at: 2026-11-01T14:44:39Z}
verified:
  - {by: okf-wiki/claude-haiku-5-5, at: 2026-11-01T14:44:39Z, commit: bae30dea28b6}
  - {by: okf-wiki/claude-opus-5-5, at: 2026-11-17T03:10:15Z, commit: 1ff103651bb4}
sources:
  - {id: measure-2026-11-01, resource: "local measurement 2026-11-01 on 5,270 queued_command prompts from a real Claude transcript corpus"}
  - {id: measure-2026-11-16, resource: "local measurement 2026-11-16 on 6,153 queued_command prompts from the same corpus"}
---

# Compaction summaries quote earlier prompts; substring dedupe drops real ones

## Symptom

Real user prompts disappear from the transcript index. They were typed mid-turn as `queued_command` attachments, and a later user record appears to repeat them [^measure-2026-11-01].

## What fails

A substring test ("this prompt appears anywhere in a user record") matches inside `isCompactSummary` records. Those summaries list every earlier user message. Of 5,270 queued prompts, 245 matched this way, all inside user records more than 2,000 characters longer than the prompt [^measure-2026-11-01].

## What works

Treat a user record as a repeat only when its text equals the prompt, or starts or ends with it, **and** it is the next human turn after the prompt. Matching any turn in the session was wrong too: an earlier `go` swallowed every later queued `go`, which hid the user's merge approvals from readers. Across 6,153 queued prompts, about 43 matched some turn, but only 2 matched one within 40 records after them, and both of those were separate prompts [^measure-2026-11-16].

## Why

Compaction writes the full prompt history into one record, so any short prompt is a substring of it. Anchoring the match to the record's start or end keeps wrapper duplicates and drops quoted summaries. The rule matches what the sample shows.

## Verify

- `modules/agent-transcripts/skills/transcript-ingest/transcripts.py` :: `parse_claude`

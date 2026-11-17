---
type: gotcha
title: Compaction summaries quote earlier prompts; substring dedupe drops real ones
description: parse_claude drops queued prompts that a user record repeats; a compaction summary quotes every earlier prompt, so match exact or start/end, never substring, or real prompts vanish.
tags: [injection]
generated: {by: okf-wiki/claude-haiku-5-5, at: 2026-11-01T14:44:39Z}
verified:
  - {by: okf-wiki/claude-haiku-5-5, at: 2026-11-01T14:44:39Z, commit: bae30dea28b6}
sources:
  - {id: measure-2026-11-01, resource: "local measurement 2026-11-01 on 5,270 queued_command prompts from a real Claude transcript corpus"}
---

# Compaction summaries quote earlier prompts; substring dedupe drops real ones

## Symptom

Real user prompts disappear from the transcript index. They were typed mid-turn as `queued_command` attachments, and a later user record appears to repeat them [^measure-2026-11-01].

## What fails

A substring test ("this prompt appears anywhere in a user record") matches inside `isCompactSummary` records. Those summaries list every earlier user message. Of 5,270 queued prompts, 245 matched this way, all inside user records more than 2,000 characters longer than the prompt [^measure-2026-11-01].

## What works

Treat a user record as a repeat only when its text equals the prompt, or starts or ends with it. In the same sample, 34 duplicates were exact and 10 were wrapped at the start or end. The rule in `parse_claude` drops only those [^measure-2026-11-01].

## Why

Compaction writes the full prompt history into one record, so any short prompt is a substring of it. Anchoring the match to the record's start or end keeps wrapper duplicates and drops quoted summaries. The rule matches what the sample shows.

## Verify

- `modules/agent-transcripts/skills/transcript-ingest/transcripts.py` :: `parse_claude`

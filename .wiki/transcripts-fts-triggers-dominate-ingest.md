---
type: gotcha
title: Transcript ingest FTS triggers dominate insert cost
description: "transcripts.py ingest slows to hours: per-row FTS5 triggers on messages cost ~100x the insert and grow with index size; drop them and rebuild FTS once per run, not tune merges."
tags: [performance]
generated: {by: okf-wiki/claude-haiku-5-5, at: 2026-10-31T19:04:12Z}
verified:
  - {by: okf-wiki/claude-haiku-5-5, at: 2026-10-31T19:04:12Z, commit: c6fd7b12cc95}
sources:
  - {id: measure-2026-10-31, resource: local measurement 2026-10-31 on a snapshot of a real 2.3k-file transcript corpus}
  - {id: pr-130, resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/130}
---

# Transcript ingest FTS triggers dominate insert cost

## Symptom

`transcripts.py ingest` throughput falls as the corpus grows: 5.1 files/s early, 2.7 files/s later. At 883 s, insert time was 867 s against 16 s of parsing [^pr-130].

## What fails

Inserting one 1.8k-message Claude file took 28.9 s with trigger `messages_fts_ai` present and 0.27 s without it; into an empty db it took 0.3 s [^measure-2026-10-31]. Dropping secondary indexes changed nothing. FTS5 `automerge=0` and `crisismerge=64` changed nothing either [^measure-2026-10-31].

`annotate()` runs `UPDATE messages SET injected ...`, which fires the AFTER UPDATE trigger `messages_fts_au`. That re-indexes every touched row even though the indexed text never changes [^measure-2026-10-31].

## What works

Drop the per-row FTS triggers, then run `INSERT INTO messages_fts(messages_fts) VALUES('rebuild')` once per run. On the whole snapshot the one-shot rebuild took 7.5 s [^measure-2026-10-31].

Without triggers, every write that changes indexed text must be followed by that rebuild. This covers ingest inserts and cascade deletes from replaced, errored or stale files.

## Why

The trigger runs per row, and its cost grows with the index. Tuning FTS5 merge settings does not reach that cost; the measurements above show no effect from merge tuning or from dropping indexes.

## Verify

- `modules/agent-transcripts/skills/transcript-ingest/transcripts.py` :: `messages_fts_ai`

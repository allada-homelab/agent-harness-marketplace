---
type: gotcha
title: Transcript ingest FTS triggers dominate insert cost
description: "transcripts.py ingest slowed to hours: per-row FTS5 triggers on messages cost ~100x the insert; v6 drops them and builds FTS in one pass — never reintroduce triggers, run `fts` when dirty."
tags: [performance]
generated: {by: okf-wiki/deepseek, at: 2026-11-08T08:06:11Z}
verified:
  - {by: okf-wiki/claude-haiku-5-5, at: 2026-10-31T19:04:12Z, commit: c6fd7b12cc95}
  - {by: okf-wiki/deepseek, at: 2026-11-08T08:06:11Z, commit: 31eb5827c384}
sources:
  - {id: measure-2026-10-31, resource: local measurement 2026-10-31 on a snapshot of a real 2.3k-file transcript corpus}
  - {id: pr-130, resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/130}
  - {id: v6, resource: commit:8a06b4d, title: Build the full-text index in one pass instead of per-row triggers}
---

# Transcript ingest FTS triggers dominate insert cost

## Symptom

`transcripts.py ingest` throughput fell as the corpus grew: 5.1 files/s early, 2.7 files/s later. At 883 s, insert time was 867 s against 16 s of parsing [^pr-130].

## What fails

Inserting one 1.8k-message Claude file took 28.9 s with trigger `messages_fts_ai` present and 0.27 s without it; into an empty db it took 0.3 s [^measure-2026-10-31]. Dropping secondary indexes changed nothing. FTS5 `automerge=0` and `crisismerge=64` changed nothing either [^measure-2026-10-31].

`annotate()` runs `UPDATE messages SET injected ...`, which fired the AFTER UPDATE trigger `messages_fts_au` — it re-indexed every touched row even though the indexed text never changes [^measure-2026-10-31].

That failure mode is history: migration v6 drops the per-row triggers and the code owns the index instead [^v6]. Reintroducing triggers would bring the crawl back.

## What works

- A full build calls `build_fts` after the generation swap: `INSERT INTO messages_fts(messages_fts) VALUES('rebuild')` once, then records `fts_max_id` and clears `fts_dirty` [^v6]. On the snapshot above the one-shot rebuild took 7.5 s [^measure-2026-10-31].
- An incremental run indexes every id above `fts_max_id` in one batch (`_fts_add_new`); ids at or below `fts_max_id` must never be reused, or the batch misses the new rows [^v6]. `_post_ingest` merges each batch (`optimize`) before `annotate()` runs.
- A failed FTS update marks `fts_dirty`; `_fts_max_id` then returns None, so later runs skip FTS work until `transcripts.py fts` rebuilds it (it refuses before the schema is current — run `ingest` for a full build first) [^v6].

## Why

The trigger runs per row and its cost grows with the index; tuning FTS5 merge settings does not reach that cost — the measurements above show no effect from merge tuning or from dropping indexes [^measure-2026-10-31]. The one-pass/batch design does the same work in one linear sweep instead.

## Verify

- `modules/agent-transcripts/skills/transcript-ingest/transcripts.py` :: `DROP TRIGGER messages_fts_ai`
- `modules/agent-transcripts/skills/transcript-ingest/transcripts.py` :: `_fts_add_new`
- `modules/agent-transcripts/skills/transcript-ingest/transcripts.py` :: `_mark_fts_dirty`

---
type: gotcha
title: A SIGNALS_VERSION bump makes an older installed review refuse the shared index
description: "'no session signals at version' from review.py after a SIGNALS_VERSION bump: ingest rewrites the shared transcripts.db, so ingest only after the fleet pin carries the bump."
tags: [sqlite, fleet]
generated: {by: okf-wiki/unknown, at: 2026-11-17T00:24:09Z}
verified:
  - {by: okf-wiki/unknown, at: 2026-11-17T00:24:09Z, commit: bc54aae5b88b}
sources:
  - {id: signals-version, resource: "modules/agent-transcripts/skills/transcript-ingest/signals.py :: SIGNALS_VERSION = 2"}
  - {id: ingest-rewrite, resource: "modules/agent-transcripts/skills/transcript-ingest/transcripts.py :: DELETE FROM session_signals WHERE signals_version != ?"}
  - {id: review-check, resource: "modules/agent-transcripts/skills/transcript-review/review.py :: SELECT 1 FROM session_signals WHERE signals_version != ?"}
  - {id: session-2026-11-16, resource: "local work 2026-11-16 on feat-transcripts-anchors-thread: SIGNALS_VERSION bumped 1 to 2 so slash commands stay human text"}
---

# A SIGNALS_VERSION bump makes an older installed review refuse the shared index

## Symptom

After a branch bumps `SIGNALS_VERSION`, an older installed `review.py` exits and tells the user to run ingest, reporting that the index has no session signals at its own version [^review-check].

## What fails

The next ingest deletes `session_signals` rows whose `signals_version` differs from the running code and recomputes them at the new version [^ingest-rewrite]. The installed fleet plugin is an older tag, and it reads the same `~/.cache/agent-transcripts/transcripts.db` as a branch checkout. Ingesting from the branch rewrites the shared cache, and the older review then refuses it [^session-2026-11-16].

## What works

Never ingest the shared cache from a feature branch. Ingest it only after the fleet pin carries the bump.

## Why

`review.py` checks for rows at its own `SIGNALS_VERSION` and fails when none exist [^review-check]. The version is set by `SIGNALS_VERSION = 2` in `signals.py` [^signals-version].

## Verify

- `modules/agent-transcripts/skills/transcript-ingest/signals.py` :: `SIGNALS_VERSION = 2`

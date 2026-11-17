---
type: gotcha
title: Test index built from SCHEMA fails migration with duplicate column
description: "sqlite3 'duplicate column name: norm_key' in a test calling tr.build_fts or annotate: a SCHEMA-built index has user_version 0, so open_db replays MIGRATIONS; set the pragma."
tags: [sqlite, testing]
generated: {by: okf-wiki/unknown, at: 2026-11-17T00:23:45Z}
verified:
  - {by: okf-wiki/unknown, at: 2026-11-17T00:23:45Z, commit: bc54aae5b88b}
sources:
  - {id: test-review-fixture, resource: "modules/agent-transcripts/test/test_review.py :: Index.__init__ sets PRAGMA user_version = len(tr.MIGRATIONS)"}
  - {id: session-2026-11-16, resource: "local work 2026-11-16 on feat-transcripts-anchors-thread: annotate test and thread test both failed on the test_review.py Index fixture"}
---

# Test index built from SCHEMA fails migration with duplicate column

## Symptom

A test that calls `tr.build_fts` or `annotate` on an index built with `executescript(tr.SCHEMA)` fails with `sqlite3.OperationalError: duplicate column name: norm_key` from `transcripts.py _migrate` [^session-2026-11-16].

## What fails

`tr.SCHEMA` is already the migrated shape, but the index's `user_version` stays 0. `open_db` reads `user_version` and replays every migration, and the `norm_key` column already exists [^session-2026-11-16].

## What works

Set `PRAGMA user_version = len(tr.MIGRATIONS)` after the schema runs, or create the index with `tr.open_db`. The `Index` fixture in `test_review.py` does the first [^test-review-fixture].

## Why

`open_db` decides which migrations to run from `user_version` alone, not from the columns present. A schema script that skips migrations leaves the version at 0, so every later open replays them.

## Verify

- `modules/agent-transcripts/test/test_review.py` :: `PRAGMA user_version = {len(tr.MIGRATIONS)}`

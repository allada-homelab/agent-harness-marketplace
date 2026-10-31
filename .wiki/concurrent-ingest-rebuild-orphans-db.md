---
type: gotcha
title: Concurrent transcript ingest --rebuild orphans the database
description: "Never start transcripts.py ingest --rebuild while another ingest runs: it unlinks transcripts.db, so the running process writes to a deleted inode and all its work is lost."
tags: [sqlite]
generated: {by: okf-wiki/claude-haiku-5-5, at: 2026-10-31T19:04:35Z}
verified:
  - {by: okf-wiki/claude-haiku-5-5, at: 2026-10-31T19:04:35Z, commit: c6fd7b12cc95}
sources:
  - {id: incident-2026-10-31, resource: "local incident 2026-10-31: two concurrent ingest runs, /proc/<pid>/fd and sqlite3 errors captured"}
---

# Concurrent transcript ingest --rebuild orphans the database

## Symptom

A second `transcripts.py ingest --rebuild` fails with `sqlite3.OperationalError: disk I/O error` at `PRAGMA user_version`, or with `database is locked` at `BEGIN IMMEDIATE` in `_migrate` [^incident-2026-10-31].

## What fails

`ingest(..., rebuild=True)` unlinks `transcripts.db` before it opens the db [^incident-2026-10-31]. The first run keeps its open handles: `/proc/<pid>/fd` showed `transcripts.db (deleted)` and `transcripts.db-wal (deleted)` while `-shm` stayed shared. Everything that run writes goes to a deleted inode and is lost. The newcomer then hits the shared `-shm` against a db it cannot use.

## What works

Check before starting: `pgrep -af 'python.*transcripts.py ingest'`. Run `--rebuild` only when that prints nothing.

Recovery: stop every ingest process, delete `transcripts.db`, `transcripts.db-wal` and `transcripts.db-shm`, then run one rebuild. Leave `findings.db` alone; it is a separate file.

## Why

`--rebuild` removes the file out from under any process still holding it open. SQLite does not notice, and the WAL and shm files are shared by name, so the two processes diverge.

## Verify

- `modules/agent-transcripts/skills/transcript-ingest/transcripts.py` :: `def ingest`

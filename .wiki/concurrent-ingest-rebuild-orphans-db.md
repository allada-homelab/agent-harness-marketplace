---
type: gotcha
title: Concurrent transcript ingest --rebuild orphans the database
description: "transcripts.py ingest exits 75 'another ingest is running' since 0.9.0: an ingest.lock flock refuses a second run. Before 0.9.0 a concurrent --rebuild unlinked the live db and lost work."
tags: [sqlite]
generated: {by: okf-wiki/claude-haiku-5-5, at: 2026-10-31T23:35:58Z}
verified:
  - {by: okf-wiki/claude-haiku-5-5, at: 2026-10-31T19:04:35Z, commit: c6fd7b12cc95}
  - {by: okf-wiki/claude-haiku-5-5, at: 2026-10-31T23:35:58Z, commit: c755d6570ebb}
sources:
  - {id: incident-2026-10-31, resource: "local incident 2026-10-31: two concurrent ingest runs, /proc/<pid>/fd and sqlite3 errors captured"}
  - {id: pr-134, resource: "https://github.com/allada-homelab/agent-harness-marketplace/pull/134 (redesign step 1, merged 2026-10-31): ingest_lock/LockBusy, gens/ generation swap"}
---

# Concurrent transcript ingest --rebuild orphans the database

## Symptom

Before 0.9.0, a second `transcripts.py ingest --rebuild` failed with `sqlite3.OperationalError: disk I/O error` at `PRAGMA user_version`, or `database is locked` at `BEGIN IMMEDIATE` in `_migrate` [^incident-2026-10-31]. Since 0.9.0 the second run exits 75 with `another ingest is running (pid N)` [^pr-134].

## What fails (before 0.9.0)

`ingest(..., rebuild=True)` unlinked `transcripts.db` before it opened the db [^incident-2026-10-31]. The first run kept its handles: `/proc/<pid>/fd` showed `transcripts.db (deleted)` and `transcripts.db-wal (deleted)` while `-shm` stayed shared. Its writes went to a deleted inode and were lost.

## What works (0.9.0+)

`ingest()` runs under `ingest_lock`, a non-blocking flock on `<dest>/ingest.lock` [^pr-134]. A refused run raises `LockBusy` and exits 75; the dotfiles runner treats 75 as a skipped tick. A full build writes `gens/transcripts-<UTC>.db` and then swaps the `transcripts.db` symlink with `os.replace`, so the live file is never unlinked under a reader. Readers that opened the old generation keep reading it.

If a crashed build leaves a partial file in `gens/`, the next successful swap deletes it. Never edit `gens/` by hand.

## Recovery (copies before 0.9.0 only)

An old plugin loaded in a long-running session still has the old behavior. Check `pgrep -af 'python.*transcripts.py ingest'` and run `--rebuild` only when it prints nothing. Otherwise stop every ingest process, delete `transcripts.db`, `transcripts.db-wal` and `transcripts.db-shm`, then run one rebuild. Leave `findings.db` alone; it is a separate file.

## Why

Before 0.9.0, `--rebuild` removed the file out from under any process still holding it open; SQLite did not notice, and the shared WAL and shm files let the two processes diverge. The lock stops a second build, and the symlink swap means no reader holds a deleted live file.

## Verify

- `modules/agent-transcripts/skills/transcript-ingest/transcripts.py` :: `def ingest_lock`

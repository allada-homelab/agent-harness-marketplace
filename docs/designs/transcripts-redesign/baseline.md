# agent-transcripts: baseline characterization

* **Date:** 2026-10-31
* **Code measured:** `origin/main` at `c6fd7b1` (agent-transcripts 0.8.8)
* **Purpose:** the numbers a redesign is measured against. Input to the
  `transcripts-redesign` concepts brief.

All timings are wall clock on one workstation, one run each. A number marked
*inferred* was not measured directly; the text says what it was derived from.

## Corpus (the raw cache)

| harness | files | on disk | uncompressed JSON | records |
|---|---|---|---|---|
| claude | 20,686 (1,378 main, 8,367 subagent, 1,902 tool-results text files) | 7.17 GB | 6.71 GB | 2.18 M |
| dsh | 2,596 (1,742 session logs, zstd) | 1.41 GB | 4.03 GB | 2.37 M |
| pi | 93 | 0.01 GB | 0.01 GB | 4.9 k |

File sizes are heavy-tailed: claude p50 45 KB, p99 3.9 MB, max 70 MB; dsh p50
109 KB, p99 5.3 MB, max 209 MB (compressed).

Where the bytes are (share of uncompressed JSON):

* **claude:** tool results 35%, `attachment` records 30% (741 k records, all but
  SessionStart context dropped by ingest), assistant records 28%. Inside
  assistant content, thinking is 56% of bytes, tool_use 36%, text 7%.
* **dsh:** assistant messages 39%, tool results 16%, request headers 16%
  (dropped), streaming chunks 12% (1.3 M records, dropped; the full message
  follows each stream).
* About 45% of raw bytes are never indexed. Thinking is not indexed as text but
  is stored in full in the `raw` column.

## Index (`transcripts.db`) after a full rebuild

Rows: 10,516 sessions, 1,306,272 messages, 468,221 tool calls, 11,576 files.

| object | size | share |
|---|---|---|
| `messages` table | 8.74 GB | 88.6% |
| `messages_fts` (FTS5 data) | 0.48 GB | 4.8% |
| `tool_calls` table | 0.44 GB | 4.5% |
| all secondary indexes | ~0.2 GB | ~2% |
| **total file** | **9.86 GB** | |

Inside `messages`: the `raw` column holds 6.15 GB, `text` 1.39 GB. Tool-result
text is 1.04 GB of the 1.39 GB. Tool-call arguments are 0.36 GB.

## Ingest (full rebuild)

| configuration | wall clock | peak RSS |
|---|---|---|
| as shipped (per-row FTS5 triggers) | did not finish; 2.7 files/s and falling at 2.4 k of 11.6 k files after 15 min. Several hours, *inferred* from the falling rate | ~200 MB at 15 min |
| triggers dropped, FTS rebuilt once | **20 min 34 s** | **1.30 GB** |
| same, and `raw` stored empty | **12 min 46 s** (parse 127 s, insert 313 s, FTS rebuild 312 s); database 2.86 GB | **0.94 GB** |

The empty-`raw` run treats more files as duplicate sessions (1,376 vs 1,034)
because the duplicate check compares `raw`; its sizes and timings are otherwise
comparable.

Phase split of the 20.5-minute run: parse 132 s, SQLite insert 725 s, one-shot
FTS rebuild 350 s, FTS optimize 2 s, annotate ~20 s, plus startup and file
walking. 26 files failed to parse (recorded, run continued); 1,034 files were
treated as duplicate sessions.

The trigger cost was isolated on a snapshot: one 1.8 k-message file inserted in
28.9 s with the triggers and 0.27 s without. Merge tuning (FTS5 `automerge`,
`crisismerge`) did not change it.

## Export (no-op, nothing new to copy)

claude 127 s (44 docker volumes, most empty; each starts a throwaway container),
dsh 8 s, pi 0.1 s. Peak RSS under 50 MB.

## The main workload: transcript-review

Measured from the transcripts themselves (tool calls that invoked each script):

| command | calls | sessions |
|---|---|---|
| `review.py view` | 4,173 | 390 |
| `review.py record` | 3,968 | 363 |
| `review.py grep` | 1,248 | 76 |
| `query.py` | 157 | 23 |
| `review.py rollup` | 121 | 61 |
| `sweep.py` | 86 | 22 |
| `review.py queue` | 67 | 34 |
| `search.py` (full-text search) | 41 | 15 |
| `excerpt.py` (full-text search) | 28 | 6 |

Of the 9,889 calls in this table, review commands are 97% and the two
full-text search scripts 0.7% (69). The callers are mostly agents running the
skills; the window is the whole indexed history. Full-text search is used by `search.py` and
`excerpt.py` only; review never uses it (`grep` is a regex over one session in
Python).

Latency against the full index (one run each, includes `uv run` start-up of
roughly 0.1 s):

| command | time | peak RSS |
|---|---|---|
| `view`, 3 k-message session | 0.13 s | 30 MB |
| `view`, 14.7 k-message session | 0.25 s | 46 MB |
| `grep`, 3 k-message session | 0.13 s | 28 MB |
| `grep`, 14.7 k-message session | 0.38 s | 29 MB |
| `queue --unreviewed --limit 20` | 4.5 s | 31 MB |
| `sweep` (whole corpus) | 25.6 s | 45 MB |

## Defects found while measuring

* **Duplicate dsh sessions.** dsh now writes `session.v4.jsonl.zstd` beside the
  v3 file. Ingest only skips the legacy `session.jsonl.zstd` when a v3 file
  exists, so v3 and v4 are both indexed: 348 duplicate `(harness, native_id)`
  pairs. `review.py view <id>` exits 1 on any of them ("matches several
  sessions").
* **Concurrent rebuilds destroy each other.** `ingest --rebuild` unlinks the
  database while another ingest holds it open; that run's work is lost and the
  new one fails with "disk I/O error" or "database is locked".
* **`annotate` rewrites `messages` on every ingest**, and the AFTER UPDATE FTS
  trigger re-indexes every row it touches.
* The `SCHEMA` string in `transcripts.py` is an unused copy of the migrations.

## What the numbers say

* Review commands are already sub-second; most of their time is interpreter
  start-up. A faster language cannot improve them in a way a person or agent
  would notice.
* `queue` (4.5 s) and `sweep` (26 s) are the slow parts of review, because they
  recompute corpus-wide signals on every call.
* Ingest time is mostly SQLite writes (725 s), and 62% of the database is the
  `raw` column, which duplicates the raw cache. Parsing is 132 s of 1,234 s.
* Peak RSS of the full rebuild is 1.3 GB; the review path stays under 50 MB.
* Not storing `raw` alone cuts the rebuild from 20.5 to 12.8 minutes, the
  database from 9.9 GB to 2.9 GB, and peak RSS from 1.3 to 0.9 GB. That change
  works in any language.
* What remains is insert 313 s, the FTS build 312 s and parse 127 s. Full-text
  search serves 0.7% of calls (69), so its 5-minute build is a candidate
  to move out of ingest. Parse is the only phase a compiled language clearly
  shortens; insert speed depends mostly on per-row statements, per-file
  transactions and the seven secondary indexes on `messages`.
* A normal run after an export parses a handful of changed files and takes
  seconds in any language. A full re-parse happens on `--rebuild` and on every
  `PARSER_VERSION` bump (now at 7), so its cost still matters.

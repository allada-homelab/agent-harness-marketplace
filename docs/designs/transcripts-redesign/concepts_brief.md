# agent-transcripts redesign

* **Author:** davidallada
* **Date:** 2026-10-31
* **Status:** brainstorm, after one Goldfish review round (six lenses)
* **Measured baseline:** [baseline.md](./baseline.md)

## Overview

agent-transcripts copies Claude Code, pi and dsh session logs into an on-device
archive (the raw cache), indexes them into a SQLite database
(`transcripts.db`), and serves the transcript-review skill, which an agent uses
to read one flagged session at a time and record findings in `findings.db`.

As shipped, a full rebuild of the index does not finish in practical time
(per-row full-text-search triggers; several hours, inferred from the measured
rate). With the triggers removed it takes 20.5 minutes, peaks at 1.3 GB of RAM
and writes a 9.9 GB database, 62% of which is a `raw` column that copies the
archive. Review itself is not slow: `view` and `grep` answer in 0.1 to 0.4 s.
The slow review steps are `queue` (4.5 s) and the sweep that feeds it (26 s),
because both recompute corpus-wide signals on every call.

The goal is an index that rebuilds in minutes, stays small, and keeps every
existing review finding valid. The language stays Python.

## Analysis

The first concept proposed a schema redesign: stable `UNIQUE(harness,
native_id)` keys, tool results merged into the tool-call row, `WITHOUT ROWID`
session clustering, an archive pointer instead of `raw`, and ingest-time review
signals. The review found that four of those parts are wrong as written and
that targeted changes reach the same targets with less risk.

**Parts of the first concept that would lose or corrupt data**

1. **Session ids are not unique.** Distinct sessions share an id by design:
   every Claude workflow `journal.jsonl` becomes id `journal`, and some
   subagent ids repeat (one appears three times in the current index). Ingest
   compares content before treating two sessions as duplicates. A UNIQUE
   constraint would merge or reject real sessions.
2. **Merging tool results into tool calls renumbers ords.** Each tool result is
   its own message row today and has its own `ord` (the position number shown
   as `[42]` in `review.py view`). `findings.db` stores those ords as evidence
   for about 4,000 recorded verdicts, and `record` checks quotes against them.
   Renumbering would point old findings at the wrong messages. The parser also
   keeps only call id and error flag per result, so there is no per-call result
   text to merge yet.
3. **Removing `raw` breaks the duplicate check.** `raw` has one reader: the
   check that compares a session's first and last records. The measured run
   with `raw` empty collapsed about 340 more sessions as duplicates. A small
   per-session fingerprint (hash of the first and last kept records plus the
   message count) replaces it.
4. **`WITHOUT ROWID` conflicts with full-text search**, which joins on the
   message's integer rowid in `search.py`, `excerpt.py`, the query docs and the
   tests. Rows inserted session by session are already stored close together.

**The archive pointer has no reader.** Nothing reads `raw` except the duplicate
check, and the review, sweep and analyze skills forbid opening raw files. The
archive is also not immutable: export overwrites changed files in place, and
dsh rewrites whole histories into new version files. Some rows match no byte
range at all (reduced SessionStart records, separate tool-result files). The
pointer is dropped.

**The targets are reachable with targeted steps.** Dropping `raw` already
meets the size target (2.86 GB measured). Moving the full-text index build out
of ingest removes 312 s. The insert phase (313 s) has known fixes: batched
statements, linking results to calls in Python instead of one UPDATE per
result, creating secondary indexes after the bulk load, and dropping indexes
on low-selectivity columns. Whether the remainder fits in 5 minutes must be
measured after each step.

**Review signals need one home.** The sweep rules live in `sweep.py` and the
queue heuristics in `review.py`. If ingest computes signals, there should be
one `signals` module, raw per-session counters stored in `transcripts.db`
(thresholds applied at query time), and a separate `SIGNALS_VERSION` so a rule
change recomputes from stored rows without re-parsing. `findings.db` keeps only
verdicts, which cannot be regenerated. Measure `queue` on the smaller database
first: a small per-session statistics table may be enough.

**Missing from the first concept:**

* `annotate` (the `injected` flag: text that appears in three or more
  sessions) spans the whole corpus, so it cannot be computed per session at
  ingest. It should write only changed rows.
* Rebuild and locking semantics: take an exclusive lock on a separate lock
  file, build into a new file and rename it into place, and say whether export
  and the full-text build take the same lock. Whether the lock works across a
  dev-container bind mount is unconfirmed.
* The schema is a public interface: `query.py` runs ad-hoc SQL, and the skill
  docs document `tool_result` rows, `result_message_id` and numeric ids.
* Shared code has no allowed home yet: `lib/` is forbidden, and today scripts
  reach into sibling skill directories.

## Goals vs. Non-Goals

* **In-scope goals:**
  * Full rebuild under 5 minutes, measured with and without the optional
    full-text build (decide which counts).
  * Database under 3 GB.
  * Peak RAM bounded by the largest session; the 300 MB target is kept only if
    something depends on it.
  * `review.py queue` under 0.5 s.
  * Every stored `evidence_ord` in `findings.db` still resolves to the same
    quote.
  * `review view` works on every session that is a duplicate today.
  * Two concurrent ingests can no longer destroy each other.
* **Out-of-scope non-goals:**
  * A Rust rewrite (see Alternatives).
  * Merging tool results into tool-call rows.
  * Pointers into the raw archive.
  * Renumbering ords or changing `findings.db` keys.
  * Real-time review signals: they may lag until the next ingest.

## Alternatives Weighed

* **Rust rewrite.** Rejected by the owner (2026-10-31), no revisit condition.
  Parse is 127 s of a 12.8-minute rebuild, review commands are already 0.1 to
  0.4 s, and a compiled binary needs per-platform distribution to every host
  and dev container while the scripts need only `uv`.
* **DuckDB.** Rejected by the owner (2026-10-31). Review reads one session in order and does point
  lookups (a row-store workload), DuckDB cannot have a writer and a reader
  open at once, and its full-text extension rebuilds from scratch on every
  change.
* **Tantivy (a Rust search library) instead of FTS5.** Rejected. Full-text
  search is 0.7% of calls (69 of 9,889) and review never uses it.
* **`UNIQUE(harness, native_id)` session key.** Rejected: distinct sessions
  share ids.
* **Tool results merged into `tool_calls`.** Deferred: renumbers stored
  evidence ords, and no target needs it.
* **Archive pointer (file, offset, length).** Dropped: no reader, and the
  archive changes under it.
* **`WITHOUT ROWID` message table.** Dropped: breaks the full-text join, and
  sessions are already stored together.
* **One big redesign PR.** Rejected in favour of staged PRs, each re-measured.

## Key Decisions & Staging for Next Steps

Staged plan, one PR and one re-measurement per step (same machine, same
corpus snapshot, cold and warm runs, median of three, peak RSS from
`/usr/bin/time -v`; the benchmark script is committed):

1. **Lock and atomic rebuild.** Exclusive lock file; rebuild into a new
   generation file and atomically swap the `transcripts.db` symlink to it
   (decided during drafting: renaming a file over a WAL-mode database risks
   pairing it with the old file's `-wal`/`-shm`; the symlink swap was tested).
2. **dsh file selection.** Index only the highest `session.vN` per session
   directory; fail loudly if two remain. Confirm v4 is a superset of v3 on real
   files and add a v4 fixture.
3. **Drop `raw`.** Add the per-session fingerprint for the duplicate check;
   bump `PARSER_VERSION`.
4. **Full-text index out of ingest.** No per-row triggers; build it once, as a
   separate step. Decide whether search fails with a "build the index" hint or
   builds it on demand.
5. **Insert speed.** Batched statements, result linking in Python, indexes
   after bulk load, fewer indexes; `annotate` writes only changed rows.
6. **Queue and sweep.** Re-time on the new database. Add per-session
   statistics and a `signals` module with its own version only if still slow.
7. **Streaming reads.** Only if the memory target is real.

**Decisions taken after the review round (2026-10-31):**

* **Session key:** keep the content comparison, now on the per-session
  fingerprint. Deriving ids from paths would change the `(harness, native_id)`
  key that existing `findings.db` verdicts use.
* **Shared code:** a stdlib-only package inside the transcript-ingest skill
  (for example `transcript-ingest/agent_transcripts/`). No repo-shape change;
  `lib/` stays forbidden.
* **Targets:** peak RAM is bounded by the largest session (measure the worst
  session) instead of a fixed 300 MB. The 5-minute rebuild target excludes the
  optional full-text build, which is measured and reported separately.
* **Dev containers:** they do not mount the transcript cache (they mount only
  per-repo `uv` and Go caches), so the cache and the lock are host-only.

**New facts found while deciding:**

* An hourly systemd user timer (`agent-transcripts.timer`, managed by the
  dotfiles `bootstrap transcripts`) runs export and ingest against the live
  cache. A manual `--rebuild` that crosses the hour collides with it, so the
  lock (step 1) is required, not optional.
* The service reports failure on every run while any file fails to parse,
  because `ingest` returns the parse-error count as its exit code. 26 claude
  files currently fail with `JSONDecodeError` on line 1. Step 1 should separate
  "a file failed to parse" (recorded, warned) from "the run failed" (exit
  non-zero), and the 26 files need a look: possibly copied mid-write by the
  non-atomic export.

**Still open:**

* Schema compatibility: keep compatibility views, or a documented break with
  skill doc rewrites? Decide per staged PR; none of steps 1 to 5 change a
  documented table or column except dropping `raw`.
* Is export (127 s no-op across 44 docker volumes) in scope?

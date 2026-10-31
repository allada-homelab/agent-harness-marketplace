# agent-transcripts: a faster, smaller transcript index

*   **Author:** davidallada
*   **Status:** Approved (2026-10-31)
*   **Date:** 2026-10-31
*   **Predecessors:** [concepts_brief.md](./concepts_brief.md),
    [baseline.md](./baseline.md)

--------------------------------------------------------------------------------

## Overview

The `agent-transcripts` module keeps a private, on-device record of coding-agent
sessions from Claude Code, pi and dsh. It has three stores:

*   **The raw cache** (the archive): byte-for-byte copies of each harness's
    session logs, written by `export`. It is the permanent record.
*   **`transcripts.db`**: a SQLite index of sessions, messages and tool calls,
    built from the raw cache by `ingest`. It can always be rebuilt.
*   **`findings.db`**: verdicts that reviewers recorded about sessions. It cannot
    be rebuilt, so nothing in this design may invalidate it.

The main consumer is the transcript-review skill: an agent asks for a queue of
sessions worth reading, views one session, searches it for evidence, and
records a verdict whose quotes are checked against the index. Review accounts
for 97% of the 9,889 recorded calls to the module's scripts.

This design changes how the index is built and stored so that a full rebuild
takes minutes instead of hours, the index is about a third of its current size,
concurrent runs cannot destroy each other, and the review queue answers
quickly. It does this in seven small, separately measured steps, in Python.

## The Problem

**A full rebuild does not finish in practical time.** As shipped, every
inserted message fires a full-text-search trigger whose cost grows with the
index. A rebuild started on 2026-10-31 slowed from 5.1 to 2.7 files per second
in its first 15 minutes, with 9,000 of 11,600 files still to go; it would have
taken several hours (inferred from the rate). A full re-parse is not rare: it
runs on every `--rebuild` and on every `PARSER_VERSION` bump, and the parser is
on version 7.

**The index copies the archive.** The database reached 9.9 GB. 6.15 GB of that
is the `raw` column, which stores every message's original JSON line again even
though the raw cache already holds it. Its only reader is the check that
detects duplicate sessions.

**Two runs at once destroy each other.** `ingest --rebuild` deletes the database
file while another ingest may have it open. The running process keeps writing
to the deleted file and loses all its work; the new one fails with "disk I/O
error" or "database is locked". This is not hypothetical: an hourly systemd
timer runs export and ingest against the same cache, so any manual rebuild that
crosses the hour collides with it. This happened twice on 2026-10-31.

**The scheduled run always reports failure.** `ingest` exits with the number of
files that failed to parse. 26 files currently fail, so the timer's service
shows "failed" every hour even when the index is complete, and a real failure
looks the same as a normal run.

**Review sees duplicate sessions.** dsh now writes a `session.v4` log beside the
older `session.v3` log for the same session, and ingest indexes both. 348
session ids appear twice, and `review.py view` refuses to open any of them.

**The review queue recomputes everything on every call.** `review.py queue`
(4.5 s) and the sweep that feeds it (26 s) scan the whole corpus each time they
run, although their inputs change only when ingest runs.

**Memory use is higher than it needs to be.** A full rebuild peaks at 1.3 GB
of RAM because parsers read whole files and keep every message's raw JSON.

What is *not* a problem: reading a session. `view` and `grep` answer in 0.1 to
0.4 s, mostly interpreter start-up. The design must not make them slower.

## Goals

Measured on the same machine and the same corpus snapshot as
[baseline.md](./baseline.md), reporting the median of three runs, cold and warm
page cache separately, peak memory from `/usr/bin/time -v`.

*   **Full rebuild in under 5 minutes**, not counting the optional full-text
    index build, which is measured and reported separately. (Today: several
    hours as shipped; 20.5 minutes with the triggers removed.)
*   **Index under 3 GB** for today's corpus. (Today: 9.9 GB.)
*   **Peak memory of a rebuild bounded by the largest session**, with the
    worst session's figure reported. (Today: 1.3 GB.)
*   **`review.py queue` in under 0.5 s.** (Today: 4.5 s.)
*   **No stored finding changes meaning.** Every `evidence_ord` already in
    `findings.db` resolves to the same quote after the change.
*   **`review.py view` opens every session**, including the 348 that are
    duplicated today.
*   **Concurrent runs are safe.** A second ingest started while one is running
    exits with a clear message and changes nothing; a crash while holding the
    lock leaves no stale lock.
*   **The scheduled run reports failure only when the run failed.** Files that
    fail to parse are recorded and reported, not turned into the exit code.
*   **Each step ships as its own pull request with its own measurement**, so a
    step that does not pay for itself can be dropped.

## Non-Goals

*   **A Rust rewrite, or DuckDB.** Decided by the owner on 2026-10-31: the
    module stays Python on SQLite. If the goals are missed, the response is
    another measured step in Python, not a language or engine change.
*   **Changing ords or `findings.db` keys.** A message's `ord` (its position
    number in `view`) and the `(harness, native_id)` session key stay as they
    are, because recorded verdicts depend on both.
*   **Merging tool results into tool-call rows.** It would renumber ords and no
    goal needs it.
*   **Pointers from the index into the raw cache.** Nothing would read them, and
    export rewrites archive files in place.
*   **A different database engine or search library.** SQLite and its FTS5
    full-text index stay.
*   **Real-time review signals.** The queue may lag behind the raw cache until
    the next ingest.
*   **Faster export.** A no-op export takes 127 s across 44 docker volumes; that
    is a separate problem.
*   **New review features.** The rubric, the view format and the record
    contract do not change.

## Open Questions

*   **Schema compatibility for ad-hoc SQL.** `query.py` runs arbitrary SQL, so
    every column is effectively public. Dropping `raw` is the only documented
    column this design removes; decide per pull request whether a change needs
    a compatibility view or a documented break.
*   **The 26 files that fail to parse.** They fail on line 1 with JSON errors;
    the cause (possibly a copy taken mid-write by the non-atomic export) is not
    yet confirmed.
*   **Is v4 a complete superset of v3** for every dsh session that has both? To
    be confirmed on real files before step 2 picks the highest version.

## Critical User Journeys (CUJs)

### CUJ 1: Review a flagged session

*   **Given**: the index is current and `findings.db` holds earlier verdicts.
*   **When**: an agent runs `review.py queue --unreviewed`, then `view` on the
    top session, `grep` for a claim's evidence, and `record` with a verdict.
*   **Then**: the queue returns in under 0.5 s; `view` and `grep` are no slower
    than today; `record` accepts quotes exactly as today; earlier verdicts still
    point at the same messages.

### CUJ 2: Rebuild after a parser change

*   **Given**: `PARSER_VERSION` was bumped, so every file must be re-parsed.
*   **When**: the next ingest runs (scheduled or by hand).
*   **Then**: it finishes in under 5 minutes, readers keep seeing the previous
    complete index until the new one is ready, and the index is under 3 GB.

### CUJ 3: A manual rebuild overlaps the hourly timer

*   **Given**: someone runs `ingest --rebuild` at 15:55; the timer fires at
    16:00.
*   **When**: the timer's ingest starts while the rebuild still runs.
*   **Then**: the timer's run exits at once with "another ingest is running" and
    changes nothing; the rebuild completes normally; no work is lost.

### CUJ 4: Some transcript files are malformed

*   **Given**: a few files in the raw cache are not valid JSONL.
*   **When**: the scheduled ingest runs.
*   **Then**: those files are recorded with their errors and listed in the
    output, the rest are indexed, and the run exits 0. It exits non-zero only
    if the run itself failed (for example, the database could not be written).

### CUJ 5: Look at a dsh session that has both v3 and v4 logs

*   **Given**: a dsh session directory holds `session.v3.jsonl.zstd` and
    `session.v4.jsonl.zstd`.
*   **When**: ingest runs, then an agent runs `review.py view <id>`.
*   **Then**: only the v4 log is indexed, and `view` opens the session.

## Technical Plan (Architecture)

### What stays the same

*   The three stores and who writes them: `export` writes the raw cache,
    `ingest` writes `transcripts.db`, review and sweep write `findings.db`.
*   The tables `files`, `sessions`, `messages` and `tool_calls`, and every
    column except `messages.raw`. Tool results remain their own `messages` rows
    with their own `ord`. Sessions are still identified by
    `(harness, native_id)`.
*   Readers (`review.py`, `sweep.py`, `query.py`, `search.py`, `excerpt.py`)
    keep opening `<cache>/transcripts.db` read-only. Steps 1 to 5 change no
    reader code except the full-text-search readers in step 4.
*   SQLite in WAL mode (one writer and any number of readers at once), and FTS5
    for full-text search.

### Data flow after the change

```text
 harness logs ──export──▶ raw/ (archive; each copy written to a temp
 (host + docker volumes)        file, then renamed into place)
                                   │
                                   ▼
                 ingest ── holds <cache>/ingest.lock (exclusive, non-blocking)
                   │
       ┌───────────┴───────────────────────────┐
       │ full build (--rebuild, schema change, │ incremental (normal hourly run)
       │ or PARSER_VERSION change)             │
       ▼                                       ▼
 gens/transcripts-<UTC>.db              current generation, in place
 bulk load, no secondary indexes,       one transaction per file,
 then CREATE INDEX, then swap the       only new/changed/removed files
 transcripts.db symlink to it
       └───────────────┬───────────────────────┘
                       ▼
           annotate (writes only rows whose `injected` changes)
                       │
                       ▼
           fts (separate step; one batch, not per-row triggers)

 readers ──open──▶ transcripts.db ─symlink─▶ gens/transcripts-<UTC>.db
```

### 1. One writer at a time, and rebuilds that never destroy the live index

**Lock.** `ingest`, `annotate` and the full-text build take an exclusive,
non-blocking `fcntl.flock` on `<cache>/ingest.lock`. If it is held, the
command prints "another ingest is running (pid N)" and exits with code 75
(the conventional "temporary failure" code), having changed nothing. The
kernel releases the lock when the process exits or crashes, so there is never
a stale lock to clean up. The cache is only used on the host (dev containers do
not mount it), so the lock does not need to work across container mounts.

**Generations.** A full build writes a new file, `gens/transcripts-<UTC
timestamp>.db`, never the file readers have open. When it completes, ingest
creates a symlink to it beside `transcripts.db` and renames that symlink over
`transcripts.db` in one atomic step. Measured on SQLite 3.53.1: SQLite follows
the symlink and keeps `-wal`/`-shm` beside the real file, readers opened before
the swap keep reading the old generation, and readers opened after it see the
new one. Ingest then deletes older generations; on Linux, a reader that still
has one open keeps reading it until it closes. The first full build after this
change replaces today's plain `transcripts.db` file the same way and removes
its leftover `-wal`/`-shm` files.

**When a full build happens.** On `--rebuild`, when the schema version changes,
and when `PARSER_VERSION` changes (every file would be re-parsed anyway, and a
fresh generation is faster and keeps readers on a complete index meanwhile).
A `meta` table records the parser version and schema version a generation was
built with. Every other run is incremental, in place, as today.

**Exit codes.** 0 when the run completed, even if some files failed to parse
(they are recorded in `files` with `status='error'` and listed on stderr with a
count); 1 when the run itself failed; 75 when another run holds the lock. The
dotfiles runner script (`scripts/agent-transcripts-run.sh`, which today turns
any non-zero ingest exit into 1) treats 75 as "skipped" (paired dotfiles
change), so a skipped hourly run is not reported as a failure.

**Atomic export.** `export` writes each copied file to a temporary name in the
same directory and renames it into place, keeping the source mtime. Ingest can
then never read a half-copied file, which may be how some of today's 26
malformed files arose (to be confirmed). Export does not take the lock: it only
writes the archive, and renames make each file appear whole.

### 2. One log per dsh session

File selection keeps, per dsh session directory, only the highest-numbered
`session.vN.jsonl.zstd`, falling back to the legacy `session.jsonl.zstd` only
when no versioned file exists. Two files surviving for one directory is a bug
and fails the run loudly, so a future `v5` cannot silently double-index again.
The existing stale-row cleanup removes the v3 rows on the next incremental run;
no rebuild is required.

### 3. No `raw` column; a fingerprint for the duplicate check

Parsers still read each record's original JSON line, but no longer store it.
Each parsed session gets a `fingerprint`: a SHA-256 over the message count and
the original lines of its first and last kept records, the same evidence the
duplicate check compares today. `sessions.fingerprint` replaces the `raw`
comparison, and an index on `sessions(harness, native_id)` replaces today's
full scan of `sessions` for every file. Distinct sessions that share an id (for
example every workflow `journal.jsonl`) still have different fingerprints and
are both kept. Dropping the column is a schema change, so it ships as a full
build into a new generation (section 1) together with a `PARSER_VERSION` bump.

### 4. Full-text search outside the ingest hot path

The three per-row FTS triggers are removed. A new `transcripts.py fts`
subcommand builds the `messages_fts` index in one statement (FTS5 `rebuild`;
312 s for today's corpus) and records in `meta` the highest message id it
covers. A full build runs it at the end, after the swap, so review never waits
for it. An incremental ingest adds the new messages' text to the index in one
batch at the end of the run and removes the text of messages it deleted before
deleting them; whether that batch stays cheap on a large index is measured in
this step. `search.py` and `excerpt.py` check `meta` and refuse to answer from a
missing or stale index, because a stale external-content index can return rows
whose text has since changed. They print "full-text index is stale; run
`transcripts.py fts`" and exit 2 (decided by the owner on 2026-10-31; building
on demand and falling back to a `LIKE` scan were rejected). Searches therefore
fail for about 5 minutes after each full build, while the build's own
`fts` step runs.

### 5. Faster inserts

*   A full build creates the tables without secondary indexes, inserts with
    `executemany` and assigns row ids in Python, so a whole file's messages,
    tool calls and result links go in as batches. Results are linked to their
    calls in Python from the call ids, not by one `UPDATE` per result. Indexes
    are created once, after all rows are in.
*   The incremental path keeps one transaction per file and uses the same
    batched inserts.
*   Indexes on low-selectivity columns (`messages_role`, `messages_injected`,
    `messages_harness`) are dropped if no measured query regresses: `stats`,
    `annotate`, `search.py` and `review.py queue` are timed with and without
    them.
*   `annotate` computes the set of injected messages and updates only rows
    whose flag differs, instead of clearing and resetting the flag on the whole
    table every run.

### 6. Review queue and sweep (only if still slow after step 5)

Re-time `review.py queue` and `sweep.py` on the smaller index first. If `queue`
is still over 0.5 s, move the per-session rules (sweep's `SessionState`, the
queue's correction and boilerplate patterns) into one module,
`skills/transcript-ingest/agent_transcripts/signals.py`, and have ingest store
raw per-session counters in a `session_signals` table with a
`SIGNALS_VERSION`. Thresholds stay at query time. A changed `SIGNALS_VERSION`
recomputes signals from the stored rows without re-parsing. `queue` then reads
one small table and attaches `findings.db` for review history. `findings.db`
keeps only verdicts and is never written by ingest.

### 7. Streaming reads (only if the memory goal is missed)

Parsers read files line by line instead of loading them whole. A session still
has to be held in memory as a unit (dsh events are sorted by sequence number,
and Claude's main-path marking walks back from the last record), so peak memory
is bounded by the largest session, not by one line. The worst session's
footprint is measured and reported.

### Rollout

Each step is one pull request in agent-harness-marketplace that bumps the
module version in its three manifest files and is measured against
[baseline.md](./baseline.md). Each merge needs the paired dotfiles change that
moves the `agents/modules.tsv` pin; step 1 also changes the runner script so
exit code 75 counts as a skipped run. Rollback for any step is moving the pin back and,
when that step changed the schema, running the older version's `ingest
--rebuild` once: an older version refuses a newer schema rather than writing
to it (today's behavior, kept). Ingest must never rebuild automatically over a
newer schema, because Claude, pi and dsh each install their own copy of the
module and can sit at different versions while a pin bump propagates; two
copies rebuilding over each other would never settle.

## Alternatives Considered

### Alternative A: Rewrite the module in Rust

*   **Pros**: Parsing (127 s of a 12.8-minute rebuild) would likely shrink to
    seconds; per-row insert overhead would drop; lower and more predictable
    memory.
*   **Cons**: Review commands are already 0.1 to 0.4 s, mostly start-up, so the
    main workload gains nothing a user would notice. The largest measured costs
    (the `raw` column, per-row FTS triggers, per-row statements) are schema and
    query problems that a rewrite would not remove by itself. A compiled binary
    must reach every host and dev container: committed per-platform binaries,
    a Rust toolchain everywhere, or a download step with checksums, where the
    Python scripts need only `uv`.
*   **Reason for Rejection**: The cost is certain and the benefit is limited to
    a full rebuild. Rejected by the owner on 2026-10-31, with no revisit
    condition.

### Alternative B: DuckDB instead of SQLite

*   **Pros**: Column storage scans aggregates (sweep, token totals) faster; reads
    Parquet directly.
*   **Cons**: Review reads one session in order and does point lookups, which is
    a row-store workload. DuckDB allows one read-write process or several
    read-only ones, never both, so a review during the hourly ingest would
    fail. Its full-text extension rebuilds the whole index on every change. The
    largest aggregate today, the sweep over 0.5 M tool calls, takes 26 s, and
    how much of that is SQLite rather than Python is not yet measured; step 6
    re-times it before anything is changed.
*   **Reason for Rejection**: It is weaker at the main workload and cannot have
    a reader and a writer at the same time. Rejected by the owner on
    2026-10-31.

### Alternative C: Tantivy (a Rust search library) instead of FTS5

*   **Pros**: Better ranking (BM25), phrase queries, snippets, cheap
    incremental commits; would replace `search.py`'s `LIKE '%…%'` scans.
*   **Cons**: A second store that can drift from SQLite, a compiled dependency,
    and new code for 0.7% of calls (69 of 9,889). Review never uses full-text
    search.
*   **Reason for Rejection**: No use case pays for it.

### Alternative D: A full schema redesign in one release

The first concept: `UNIQUE(harness, native_id)` session keys, tool results
merged into tool-call rows, a `WITHOUT ROWID` message table clustered by
session, and pointers into the raw cache instead of `raw`.

*   **Pros**: A cleaner model on paper; sweep's four-table join would become one
    table scan.
*   **Cons**: Each part fails on the current data. Distinct sessions share ids
    (every workflow `journal.jsonl` is `journal`), so a unique key merges real
    sessions. Merging tool results renumbers ords, which about 4,000 recorded
    verdicts in `findings.db` cite as evidence. `WITHOUT ROWID` breaks the
    integer-rowid join that full-text search relies on. Pointers have no reader,
    and export rewrites archive files in place. One release would also hide
    which change bought which improvement.
*   **Reason for Rejection**: It risks the one store that cannot be rebuilt, and
    staged steps reach the same targets.

### Alternative E: Keep the per-row FTS triggers and tune FTS5 merging

*   **Pros**: No change to how search stays current.
*   **Cons**: Measured on a snapshot: one 1.8 k-message file took 28.9 s with
    the triggers and 0.27 s without; `automerge=0` and `crisismerge=64` made no
    difference.
*   **Reason for Rejection**: Tuning does not touch the cost.

### Alternative F: Rebuild the full-text index from scratch after every ingest

*   **Pros**: Simplest way to keep search exact; no incremental bookkeeping.
*   **Cons**: 312 s on every hourly run that changed anything, for a feature
    used 69 times in the whole history.
*   **Reason for Rejection**: Kept only as the fallback if the incremental batch
    in step 4 turns out to be slow on a large index.

### Alternative G: A second ingest waits for the lock instead of exiting

*   **Pros**: A person who starts a run always gets it.
*   **Cons**: The hourly timer would queue behind a long rebuild and then run
    an ingest the rebuild already covered; waiting processes pile up if a run
    hangs.
*   **Reason for Rejection**: Exiting suits the scheduled case, which is the
    common one. A `--wait` flag can be added when someone needs it.

### Alternative H: Rebuild in place, or rename a finished file over `transcripts.db`

*   **Pros**: No `gens/` directory and no symlink.
*   **Cons**: Rebuilding in place is what destroys concurrent work today.
    Renaming a new file over a database in WAL mode would pair the new file
    with the old file's `-wal`/`-shm` while readers still use them, which can
    corrupt reads.
*   **Reason for Rejection**: The symlink swap was tested and keeps each
    generation's sidecar files with that generation.

### Alternative I: Derive session ids from file paths for generic file names

*   **Pros**: Makes `(harness, native_id)` unique, so a database constraint
    could enforce it.
*   **Cons**: Changes the key that existing `findings.db` verdicts use for those
    sessions.
*   **Reason for Rejection**: The fingerprint keeps today's keys and still
    tells distinct sessions apart.

--------------------------------------------------------------------------------

## Non-Functional Requirements

*   **Privacy.** Transcripts and anything derived from them never enter a git
    repository. The benchmark script prints numbers only, and its golden
    outputs (rendered `view`/`grep` text) are stored under the cache root, not
    in the repository. The existing worktree guard covers the cache root,
    `gens/` and the lock file, which all live there.
*   **Performance.** The goals above. `view` and `grep` must not get slower than
    the baseline (0.13 to 0.38 s).
*   **Rollout and rollback.** See Rollout in the Technical Plan.

--------------------------------------------------------------------------------

## Detailed Implementation Plan

Paths are relative to the agent-harness-marketplace repository unless they say
`dotfiles:`. `M` is `modules/agent-transcripts`. Every pull request also
changes the four version files listed under "Every step" and runs the
verification plan.

### Every step

#### `M/package.json`, `M/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` (Modify)

*   **Proposed Changes**: bump the module version (patch level per step). The
    three must agree; `bin/check.sh` enforces it.

#### `M/plugin.json`, `modules/index.yaml` (Regenerate)

*   **Proposed Changes**: regenerated with `bin/render-plugin-manifests.py
    --write` and `bin/render-index.py --write`; never edited by hand.

#### `dotfiles:agents/modules.tsv` (Modify, after each merge)

*   **Proposed Changes**: move the `agent-transcripts` row's ref to the new tag
    and re-render with `render-modules.py`, so all three harnesses install it.

### Step 0 (lands with step 1): benchmark and acceptance script

#### `M/test/bench_transcripts.py` (Create)

*   **Type / Scope**: stand-alone script (`uv run --script`), not collected by
    pytest (no `test_` prefix).
*   **Proposed Changes**:
    *   `rebuild --runs 3`: copies nothing; runs a full build into a scratch
        cache root whose `raw/` is a symlink to the real one, and reports wall
        time, phase timings (from the ingest stderr lines), peak RSS (via
        `/usr/bin/time -v`), and database size per table (`dbstat`).
        Reports the median of the runs; `--drop-caches` is not attempted (needs
        root), so cold runs are documented as "first run after boot or after
        reading other large files".
    *   `review --sessions N`: times `review.py queue`, and `view`/`grep` on the
        N largest sessions plus N sampled ones.
    *   `golden capture|compare`: renders `view` and `grep` output for a fixed
        sample of sessions into `<cache>/bench/golden/` and later diffs against
        it, printing only the session ids and line counts of differences.
    *   `evidence`: for every `review_flags` row with `present=1` in
        `findings.db`, checks that its `quote` is still found in the message at
        its `evidence_ord` (the same check `review.py record` applies), and
        prints the count that fail.
    *   Output contains no transcript text except in the golden files under the
        cache root.

### Step 1: lock, generations, exit codes, atomic export

#### `M/skills/transcript-ingest/transcripts.py` (Modify)

*   **Proposed Changes**:
    *   `ingest_lock(dest_root)`: context manager; opens `<dest>/ingest.lock`,
        `fcntl.flock(LOCK_EX | LOCK_NB)`, writes its pid into the file; on
        `BlockingIOError` raises `LockBusy(pid)`. Used by `cmd_ingest`,
        `cmd_annotate` and (step 4) `cmd_fts`.
    *   `MIGRATIONS` step 4: `CREATE TABLE meta (key TEXT PRIMARY KEY, value
        TEXT NOT NULL)`. Keys: `schema_version`, `parser_version`,
        `built_at`.
    *   `needs_full_build(dest_root)`: true when `--rebuild` was given, no
        database exists, the database's `user_version` is lower than
        `len(MIGRATIONS)`, or `meta.parser_version` differs from
        `PARSER_VERSION`. A higher `user_version` still raises, as today.
    *   `full_build(dest_root)`: creates `<dest>/gens/` if needed, builds
        `gens/transcripts-<UTC %Y%m%dT%H%M%SZ>.db` through `open_db` + the
        normal ingest loop, writes `meta`, runs `PRAGMA wal_checkpoint
        (TRUNCATE)`, closes it, then creates `<dest>/transcripts.db.tmp-link`
        pointing at `gens/<name>` (relative target) and `os.replace`s it onto
        `<dest>/transcripts.db`. After the swap it deletes every other file
        in `gens/` and, if the previous `transcripts.db` was a plain file,
        removes the leftover `<dest>/transcripts.db-wal` and `-shm`.
    *   `ingest(dest_root, rebuild)` becomes: take the lock; if
        `needs_full_build` → `full_build`, else the existing incremental loop
        against the current generation; then annotate. Returns an `IngestResult`
        (parsed, unchanged, errors, duplicates, removed) instead of the error
        count.
    *   `cmd_ingest`: prints the summary line as today plus
        `errors: N files failed to parse (see files.status='error')` on stderr
        when N > 0; returns 0. `LockBusy` → message on stderr, return 75. Any
        other exception propagates (Python exits 1).
    *   Export: `_write_member` and `_export_host` write to
        `<dest>.<pid>.tmp` in the same directory, set the source mtime with
        `os.utime`, then `os.replace` onto the final name. A leftover `*.tmp`
        from a crashed export is ignored by `iter_raw_files` (it already only
        matches `*.jsonl` / `session*.jsonl.zstd`) and overwritten next time.
    *   `SCHEMA` (the string the sweep and review tests build databases from)
        gains the `meta` table so test databases match.

#### `M/skills/transcript-ingest/SKILL.md` (Modify)

*   **Proposed Changes**: document the lock and exit code 75, that a full build
    happens on `--rebuild`, schema change or parser change and keeps readers on
    the previous index until it is ready, that parse errors no longer change the
    exit code, and that `gens/` must not be edited by hand.

#### `M/test/test_ingest.py` (Modify)

*   **Proposed Changes**: new tests, each one behavior:
    *   a second `ingest` while a lock holder (a subprocess holding the flock)
        is alive returns 75 and leaves the database bytes unchanged;
    *   after the lock holder is killed with SIGKILL, `ingest` succeeds (no
        stale lock);
    *   a reader connection opened before `ingest --rebuild` still sees the old
        row counts after the swap, and a new connection sees the new ones;
    *   the first full build over a plain `transcripts.db` file leaves a
        symlink, one file in `gens/`, and no `transcripts.db-wal`/`-shm` beside
        the link;
    *   a parser-version change triggers a full build (a new generation name);
    *   an unparseable file yields exit 0 from `cmd_ingest`, a `status='error'`
        row, and the stderr count line;
    *   existing `test_ingest_is_incremental_and_rebuildable` updated for the
        new return type.

#### `M/test/test_export.py` (Modify)

*   **Proposed Changes**: an exported file is never observable half-written
    (the final path appears only via `os.replace`, checked by patching
    `os.replace` and asserting the temp file is complete when it is called);
    the source mtime is preserved; a stale `*.tmp` is not ingested.

#### `dotfiles:scripts/agent-transcripts-run.sh` (Modify)

*   **Proposed Changes**: run ingest, capture its exit code; 75 → log
    "ingest skipped: another run holds the lock" and leave `status` at 0; any
    other non-zero → `status=1` as today.

### Step 2: one log per dsh session

#### `M/skills/transcript-ingest/transcripts.py` (Modify)

*   **Proposed Changes**: `iter_raw_files` groups dsh candidates by session
    directory and keeps the file with the highest `N` in `session.vN.jsonl.zstd`
    (the legacy `session.jsonl.zstd` counts as version 0). A file matching
    `session*.jsonl.zstd` that is neither form raises `ValueError` naming it,
    which fails the run (exit 1) so a new naming scheme is noticed.

#### `M/test/test_ingest.py` (Modify)

*   **Proposed Changes**: a v4 fixture built with the existing `_frame` helper;
    tests for v3+v4 → only v4 indexed; legacy+v3+v4 → only v4; an incremental
    run over an index that holds both v3 and v4 rows removes the v3 rows
    (`removed=1`); an unknown `session.foo.jsonl.zstd` fails the run.

#### Pre-merge check (no file)

*   On the real cache, for all 348 sessions with both logs, compare v3 and v4
    message counts and first/last message text with a scratch script; v4 must
    contain at least everything v3 has. Report the counts in the pull request.

### Step 3: drop `raw`, add the session fingerprint

#### `M/skills/transcript-ingest/transcripts.py` (Modify)

*   **Proposed Changes**:
    *   `MIGRATIONS` step 5: `ALTER TABLE messages DROP COLUMN raw`, `ALTER
        TABLE sessions ADD COLUMN fingerprint TEXT NOT NULL DEFAULT ''`,
        `CREATE INDEX sessions_harness_native ON sessions(harness,
        native_id)`. Because `needs_full_build` fires on a lower
        `user_version`, these statements only ever run on an empty new
        generation.
    *   `PARSER_VERSION` 8.
    *   `Session` gains `fingerprint`; `_finalize` sets it to the SHA-256 hex
        of `f"{len(messages)}\n{messages[0].raw}\n{messages[-1].raw}"` (empty
        string for a session with no messages). `Message.raw` stays in memory
        for this and for parsers that use it; it is no longer inserted.
    *   `_duplicate_session_id` becomes one indexed query:
        `SELECT id FROM sessions WHERE harness=? AND native_id=? AND
        fingerprint=? LIMIT 1`.
    *   `SCHEMA` drops `raw` and adds `fingerprint` and the new index.

#### `M/skills/transcript-query/SKILL.md`, `M/skills/transcript-ingest/SKILL.md`, `M/README.md` (Modify)

*   **Proposed Changes**: remove `raw` from the documented columns and from the
    "never select raw" guidance; add `sessions.fingerprint` with one line on its
    purpose.

#### `M/test/test_ingest.py`, `M/test/test_sweep.py`, `M/test/test_review.py`, `M/test/test_audit_tools.py` (Modify)

*   **Proposed Changes**: tests that insert rows with a `raw` value or assert on
    stored `raw` change to the new columns. New tests: two `journal.jsonl`
    sessions with different content are both kept; two byte-identical copies
    under aliased project directories keep exactly one; the stored row has no
    `raw` column.

### Step 4: full-text index outside ingest

#### `M/skills/transcript-ingest/transcripts.py` (Modify)

*   **Proposed Changes**:
    *   `MIGRATIONS` step 6: drop the three `messages_fts_*` triggers.
        (Schema change → full build.)
    *   `cmd_fts` / `build_fts(dest_root)`: under the lock, `INSERT INTO
        messages_fts(messages_fts) VALUES('rebuild')`, then `meta`
        `fts_max_id = max(messages.id)` and `fts_dirty = 0`.
    *   `full_build` calls `build_fts` after the swap (readers already see the
        new index; searches refuse until it finishes).
    *   Incremental ingest: before `_record_file` deletes a file's previous
        rows, issue FTS `delete` commands for those message ids and texts (an
        external-content index needs the old text to remove it); after the run,
        `INSERT INTO messages_fts(rowid, text) SELECT id, text FROM messages
        WHERE id > fts_max_id`, then update `fts_max_id`. If either step
        raises, set `fts_dirty = 1` and continue (the run is not failed).
    *   `SCHEMA` drops the triggers.

#### `M/skills/transcript-query/search.py`, `M/skills/transcript-query/excerpt.py` (Modify)

*   **Proposed Changes**: before querying, read `meta.fts_max_id` and
    `fts_dirty`. The index is stale when either key is missing, `fts_dirty =
    1`, or `max(messages.id) > fts_max_id`. On a stale index: print
    `full-text index is stale; run: uv run --script <ingest skill
    dir>/transcripts.py fts` to stderr (with the real path) and exit 2, without
    running the query.

#### `M/skills/transcript-query/SKILL.md`, `M/skills/transcript-ingest/SKILL.md` (Modify)

*   **Proposed Changes**: document `transcripts.py fts` and the stale-index
    behavior.

#### `M/test/test_ingest.py`, `M/test/test_query.py` (Modify)

*   **Proposed Changes**: an incrementally re-parsed file's old words are gone
    from the index and its new words are found; a removed file's words are
    gone; a full build leaves `fts_dirty = 0` and full coverage; `search.py`
    and `excerpt.py` exit 2 with the instruction when `fts_dirty = 1`, when
    `meta` has no `fts_max_id`, and when a message id exceeds `fts_max_id`,
    and answer normally after `transcripts.py fts`.

### Step 5: faster inserts

#### `M/skills/transcript-ingest/transcripts.py` (Modify)

*   **Proposed Changes**:
    *   Full build: tables created without the secondary indexes; each file's
        rows inserted with `executemany`, with `messages.id` and
        `tool_calls.id` assigned in Python from running counters so result
        links (`result_message_id`) are known before insert; one transaction
        per 200 files; the secondary indexes created after the last file.
    *   Incremental path: same batched inserts inside its per-file
        transaction; ids assigned from `max(id) + 1`.
    *   Result linking moves into Python for both paths: a per-file map from
        call id to tool-call row id replaces the per-result `UPDATE`.
    *   `annotate`: computes the target set of injected message ids with the
        existing GROUP BY, then updates only `injected = 1` rows not in the set
        and `injected = 0` rows in it.
    *   Index pruning: `messages_role`, `messages_injected`, `messages_harness`
        are dropped in `MIGRATIONS` step 7 only if the benchmark shows no
        regression in `stats`, `annotate`, `search.py` and `review.py queue`;
        otherwise they stay and this bullet is removed from the pull request.

#### `M/test/test_ingest.py` (Modify)

*   **Proposed Changes**: a full build and an incremental ingest of the same
    fixtures produce identical rows (compared table by table, ignoring ids);
    every tool result links to its call as before; a second `annotate` with no
    new data changes zero rows (`total_changes()` unchanged).

### Step 6 (only if `queue` is still over 0.5 s after step 5)

#### `M/skills/transcript-ingest/agent_transcripts/__init__.py`, `M/skills/transcript-ingest/agent_transcripts/signals.py` (Create)

*   **Proposed Changes**: `signals.py` holds the per-session rules moved from
    `sweep.py` (`SessionState`, `KINDS`, `SIGNATURES`, `SHELL_TOOLS`) and
    `review.py` (`BOILERPLATE`, `CORRECTION_RE`, `SHORT_USER`), plus
    `SIGNALS_VERSION = 1`. Stdlib only.

#### `M/skills/transcript-ingest/transcripts.py` (Modify)

*   **Proposed Changes**: `MIGRATIONS` step: `session_signals (session_id
    PRIMARY KEY REFERENCES sessions ON DELETE CASCADE, signals_version,
    message_count, last_role, ends_on_user, correction_count,
    first_correction_ord, counters TEXT /* JSON of per-kind counts */)`.
    Ingest computes a session's row after inserting it; a `SIGNALS_VERSION`
    mismatch recomputes all rows from stored messages without re-parsing.

#### `M/skills/transcript-review/review.py`, `M/skills/transcript-sweep/sweep.py` (Modify)

*   **Proposed Changes**: `queue_candidates` reads `session_signals` joined to
    `sessions`, attaching `findings.db` for review history; `sweep.py` imports
    the rules from `agent_transcripts.signals` (via the same sibling `sys.path`
    pattern `review.py` already uses) and writes `sweep_flags` from stored
    counters. Both print the signals version and when it was computed.

#### `M/test/test_review.py`, `M/test/test_sweep.py` (Modify)

*   **Proposed Changes**: queue order and `why` column identical to the
    pre-change output on the fixtures; sweep flags identical; a
    `SIGNALS_VERSION` bump recomputes without re-parsing.

### Step 7 (only if the memory goal is missed)

#### `M/skills/transcript-ingest/transcripts.py` (Modify)

*   **Proposed Changes**: `_json_lines` and the Claude/pi parsers iterate the
    file line by line instead of `read_text().split()`; `Message.raw` is kept
    only for the first and last message of a session (the fingerprint inputs).
    The benchmark reports the worst session's peak memory.

### Verification Plan

*   **Build / static checks**: `CHECK_BASE=origin/main bin/check.sh` (the
    repository gate: manifests, skill lint, version bump, private-path grep,
    pytest for every module, node suites). Baseline captured before step 1;
    each pull request reports the delta.
*   **Unit tests**: `uv run --with pytest --with pyyaml --with zstandard
    --python 3.12 pytest -q modules/agent-transcripts/test` (181 passing at
    `c6fd7b1`, plus the tests each step adds).
*   **Measurement**: `bench_transcripts.py rebuild --runs 3` and `review` on
    the real corpus after each step, compared with [baseline.md](./baseline.md)
    and recorded in the pull request.
*   **Acceptance, once, before step 1 and after every step**:
    `bench_transcripts.py golden capture` before step 1, `golden compare`
    after each step (differences must be the intended ones, listed in the pull
    request); `bench_transcripts.py evidence` reports zero failing quotes.
*   **Live check**: after each merge and pin bump, the next hourly run of
    `agent-transcripts.service` exits 0 (`systemctl --user status`), and
    `review.py view` opens a former v3/v4 duplicate.

--------------------------------------------------------------------------------

*Drafted with EGM*

---
name: transcript-ingest
description: Build or refresh the derived sqlite index over exported Claude Code, pi and dsh transcripts in the agent-transcripts cache. Use when the user wants to "index transcripts", "ingest transcripts into sqlite", or "refresh the transcript index". The database is derived and safe to delete; raw files stay canonical. Querying it is the transcript-query skill.
tags: [observability]
---

# transcript-ingest

Parses the raw transcripts the three export skills copied into the agent-transcripts cache
and writes one sqlite database beside them, so later analysis queries a single schema
instead of re-parsing three formats.

**The raw files are canonical; the database is derived.** Deleting it loses nothing — a
rebuild re-reads `raw/`. A parse failure is recorded against the file and does not stop the
run.

## The commands

```bash
# Index everything new or changed since the last run.
uv run --script ./transcripts.py ingest

# Re-parse everything into a fresh database (a parser change does this on its own).
uv run --script ./transcripts.py ingest --rebuild

# Flag standing-instruction boilerplate as `injected` (also auto-run at the end of ingest).
uv run --script ./transcripts.py annotate [--min-sessions N] [--exclude-role R]

# Rebuild the full-text index in one pass (a full build runs it on its own, after the swap).
uv run --script ./transcripts.py fts

# What is in the cache and the index.
uv run --script ./transcripts.py stats
```

Options: `--dest DIR` overrides the cache root (default `$AGENT_TRANSCRIPT_DIR`, else an
`agent-transcripts` directory inside the user's cache directory), matching the export
skills.

## One run at a time, and a live index that is never rebuilt in place

- **Lock.** `ingest`, `annotate` and `fts` take an exclusive lock on `<cache>/ingest.lock`. A
  second run started while one holds it prints `another ingest is running (pid N)`, changes
  nothing and exits **75**. The lock dies with its process, so a crash never leaves a stale
  one behind.
- **Full builds.** `--rebuild`, a schema change or a parser-version change makes ingest
  build a new database under `<cache>/gens/` and then swap the `transcripts.db` symlink
  onto it in one rename. Readers keep seeing the previous complete index until the swap;
  older generations are deleted after it. Every other run updates the current generation
  in place. Never edit or delete files under `gens/` by hand; `ingest --rebuild` is the
  way to start over.
- **Full-text index.** `messages_fts` is not updated per row. A full build runs `fts` after
  the swap (minutes on a large corpus); until it finishes, `search.py` and `excerpt.py`
  refuse with `full-text index is stale` and exit 2, while every other reader works. An
  incremental run removes a re-parsed or deleted file's old text from the index and adds
  the new messages in one batch at the end. If that update fails, the run still succeeds
  but marks the index dirty (`meta.fts_dirty = 1`), and searches refuse until `fts` runs.
  `fts` refuses (exit 1) an index whose schema is older than this code: run `ingest`.
- **Newer schema.** An index built by a newer version of this module is refused, never
  rebuilt over: each harness installs its own copy, and two versions rebuilding over each
  other would never settle.
- **Exit codes.** `ingest` exits **0** when the run completed, even when some files failed
  to parse: those are recorded with `files.status = 'error'`, listed on stderr, and
  counted in an `errors: N files failed to parse` line. It exits **1** when the run
  itself failed and **75** when another run holds the lock.
- **Torn records.** A write cut short by a full disk or a crash leaves a record without its
  tail; the harness's next append then lands on the same line. Ingest drops that fragment,
  keeps the record glued after it and the rest of the file, and prints a
  `torn: <file> line N` warning, so one lost record never drops the whole session. A torn
  final line is dropped the same way.

## Schema summary

`transcripts.db` sits beside `raw/`:

- `files` — one row per raw file: `harness`, `relpath` (unique), `size`, `mtime`,
  `parser_version`, `status`, `error`, `parsed_at`. A file is re-parsed when it is new, its
  size or mtime changed, or its recorded parser version is older than the current one.
- `sessions` — `harness`, `native_id`, the owning file, `cwd`, `project_key`, `kind`
  (`main` or `subagent`), `parent_native_id`, `started_at`, `ended_at`, `model`, `title`,
  and `fingerprint` — a SHA-256 over the message count and the first and last messages'
  id, role, timestamp and text, which ingest uses to tell a copy of a session (kept once,
  even when its lines carry different metadata, as a Claude workflow agent's second log
  does) from a different session that shares its id (both kept).
  A Claude file anywhere under a session's `subagents/` directory is a `subagent` whose
  `parent_native_id` is that session — direct subagents and Workflow agents
  (`subagents/workflows/<run>/agent-<id>.jsonl`) alike.
- `messages` — per session: `ord`, `native_id`, `parent_native_id`, `on_main_path`, `role`
  (`user`, `assistant`, `tool_result`, `system`), `ts`, `text`, `model`, `stop_reason`,
  token counts, and `injected`. The original record is not stored; the raw file is
  canonical. The token counts are
  `input_tokens`, `output_tokens`, `cache_read_tokens` and `cache_write_tokens`, as the
  harness reported them: every harness reports `input_tokens` **exclusive** of the prompt
  cache, so the prompt a turn actually processed is `input_tokens + cache_read_tokens +
  cache_write_tokens` (`NULL` cache columns mean the harness did not report them).
  Claude Code writes one row per content block of an API response, each repeating the
  response's usage, so ingest stores that usage once — each field's maximum across the
  response's rows, on its last row — and leaves the other rows' counts `NULL`. A `sum()`
  over `messages` therefore counts each API call once.
  A Claude `system` row is a SessionStart hook's injected context: only the
  `additionalContext` string (from a `hook_success` record's JSON stdout, or a
  `hook_additional_context` record), one row per distinct text per session, `injected = 1`
  from ingest on. The allowlist is strict — every other attachment (including PostToolUse
  hooks, which repeat the tool output) and any non-JSON hook stdout is skipped.
  `injected` is `1` for a message
  that is standing-instruction boilerplate — a `system` message, or any non-`tool_result`
  message whose normalized text appears in several distinct sessions (a standing instruction
  the harness prepends to every session). The `annotate` pass computes it; `ingest` runs it
  automatically at the end. The `transcript-query` skill's `search.py --exclude-injected` drops
  these so a term search reflects what sessions actually did, not the instruction text that
  appears everywhere.
- `tool_calls` — per message: `call_id`, `name`, `arguments`, the result message, `is_error`.
- `messages_fts` — an FTS5 external-content index over `messages.text`, built by `fts` and
  extended by each incremental ingest (no triggers).
- `meta` — `key`/`value` pairs recording what the generation was built with:
  `schema_version`, `parser_version`, `built_at`; and the full-text index's state:
  `fts_max_id` (the highest message id it covers) and `fts_dirty` (`1` after a failed
  update).
- `session_signals` — one row per main session, what `transcript-review`'s `queue` ranks
  by: `message_count`, `ends_on_user`, and `correction` (the first short correcting user
  turn, boilerplate stripped). Every `ingest` fills the rows its new sessions lack; the
  rules and their `signals_version` live in `signals.py`, and a version change recomputes
  every row from the stored messages without re-parsing a file.

`text` holds text blocks only (no tool arguments, no thinking). Re-parsing a file deletes
its sessions first, so rows never duplicate. A file that is no longer in the raw set loses
its rows on the next `ingest`. Each dsh session directory is indexed from its
highest-numbered `session.vN.jsonl.zstd` only (the legacy `session.jsonl.zstd` counts as
version 0), since each dsh format upgrade rewrites the whole history into the new file; an
older log loses its rows once a newer one sits beside it. A file matching
`session*.jsonl.zstd` in neither form fails the run (exit 1), so a new naming scheme is
noticed rather than indexed twice.

## Privacy invariants

- **Transcripts and anything derived from them never enter a git repo** — the database is as
  sensitive as the raw files. The worktree guard refuses a cache root inside a git worktree.
- Raw files are read, never rewritten; the exports stay the source of truth.
- Fixtures in this repo are synthetic; real transcript text is never copied into it.

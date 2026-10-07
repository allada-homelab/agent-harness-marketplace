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

# Start from an empty database (after a parser change).
uv run --script ./transcripts.py ingest --rebuild

# Flag standing-instruction boilerplate as `injected` (also auto-run at the end of ingest).
uv run --script ./transcripts.py annotate [--min-sessions N] [--exclude-role R]

# What is in the cache and the index.
uv run --script ./transcripts.py stats
```

Options: `--dest DIR` overrides the cache root (default `$AGENT_TRANSCRIPT_DIR`, else an
`agent-transcripts` directory inside the user's cache directory), matching the export
skills.

## Schema summary

`transcripts.db` sits beside `raw/`:

- `files` — one row per raw file: `harness`, `relpath` (unique), `size`, `mtime`,
  `parser_version`, `status`, `error`, `parsed_at`. A file is re-parsed when it is new, its
  size or mtime changed, or its recorded parser version is older than the current one.
- `sessions` — `harness`, `native_id`, the owning file, `cwd`, `project_key`, `kind`
  (`main` or `subagent`), `parent_native_id`, `started_at`, `ended_at`, `model`, `title`.
  A Claude file anywhere under a session's `subagents/` directory is a `subagent` whose
  `parent_native_id` is that session — direct subagents and Workflow agents
  (`subagents/workflows/<run>/agent-<id>.jsonl`) alike.
- `messages` — per session: `ord`, `native_id`, `parent_native_id`, `on_main_path`, `role`
  (`user`, `assistant`, `tool_result`, `system`), `ts`, `text`, `model`, `stop_reason`,
  token counts, the original record as `raw`, and `injected`. The token counts are
  `input_tokens`, `output_tokens`, `cache_read_tokens` and `cache_write_tokens`, as the
  harness reported them: every harness reports `input_tokens` **exclusive** of the prompt
  cache, so the prompt a turn actually processed is `input_tokens + cache_read_tokens +
  cache_write_tokens` (`NULL` cache columns mean the harness did not report them).
  Claude Code writes one row per content block of an API response, each repeating the
  response's usage, so ingest stores that usage once — each field's maximum across the
  response's rows, on its last row — and leaves the other rows' counts `NULL`. A `sum()`
  over `messages` therefore counts each API call once.
  `injected` is `1` for a message
  that is standing-instruction boilerplate — a `system` message, or any non-`tool_result`
  message whose normalized text appears in several distinct sessions (a standing instruction
  the harness prepends to every session). The `annotate` pass computes it; `ingest` runs it
  automatically at the end. The `transcript-query` skill's `search.py --exclude-injected` drops
  these so a term search reflects what sessions actually did, not the instruction text that
  appears everywhere.
- `tool_calls` — per message: `call_id`, `name`, `arguments`, the result message, `is_error`.
- `messages_fts` — an FTS5 external-content index over `messages.text`, kept in sync by
  triggers.

`text` holds text blocks only (no tool arguments, no thinking). Re-parsing a file deletes
its sessions first, so rows never duplicate. A file that is no longer in the raw set loses
its rows on the next `ingest`; that includes a dsh `session.jsonl.zstd` once a
`session.v3.jsonl.zstd` sits beside it, since dsh's v3 upgrade rewrites the whole history
into the v3 file.

## Privacy invariants

- **Transcripts and anything derived from them never enter a git repo** — the database is as
  sensitive as the raw files. The worktree guard refuses a cache root inside a git worktree.
- Raw files are read, never rewritten; the exports stay the source of truth.
- Fixtures in this repo are synthetic; real transcript text is never copied into it.

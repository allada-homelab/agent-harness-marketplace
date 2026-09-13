---
name: transcript-export-pi
description: Export pi coding-agent session JSONL from its settings and default session directories into the on-device agent-transcripts cache. Use when the user wants to "export pi transcripts" or "collect pi sessions". Read-only, incremental, never writes into a git repo.
tags: [observability]
---

# transcript-export-pi

Copies pi coding-agent session JSONL from both roots pi can write to into the shared
on-device agent-transcripts cache, so it can be indexed and analyzed without touching the
originals.

**Read-only, incremental.** Sources are never mutated; nothing is written into a git
worktree; a re-run copies only files whose size or integer mtime changed.

## What it discovers (two host roots)

1. **Settings root** — `$PI_CODING_AGENT_SESSION_DIR` when set, else the `sessionDir` value
   in `settings.json` inside pi's agent directory (`$PI_CODING_AGENT_DIR` when set, else the
   `.pi/agent` directory in the user's home). Skipped when neither names a directory.
2. **Default root** — the `sessions/` directory inside pi's agent directory. Always
   exported, unless it is the same directory as the settings root.

The two land under different tags (`settings` and `default`) so files from both roots
coexist without collision. Flat and per-cwd-slug layouts are both copied as found. Docker
volumes are not scanned for pi in v0.1; the manifest records that as skipped.

## The commands

```bash
# Always dry-run first — lists each source and the file count it would copy, writes nothing.
uv run --script ../transcript-ingest/transcripts.py export pi --dry-run

# Then the real export.
uv run --script ../transcript-ingest/transcripts.py export pi
```

Options: `--dest DIR` (override the cache root), `--json` (also print the manifest to
stdout). After exporting, build the index with the `transcript-ingest` skill.

## Output layout

The cache root is `--dest`, else `$AGENT_TRANSCRIPT_DIR`, else an `agent-transcripts`
directory inside the user's cache directory. Under it:

```
raw/pi/host/settings/<ts>_<uuid>.jsonl
raw/pi/host/default/<ts>_<uuid>.jsonl
manifest.json
```

`manifest.json` is merged per run and keyed by harness, so exporting pi leaves the claude
and dsh entries untouched:

```json
{
  "exported_at": "<iso8601 UTC>",
  "harnesses": {
    "pi": {"sources": [
      {"name": "host", "kind": "host", "origin": "...", "subdir": "settings|default",
       "files": 0, "bytes": 0, "newest_mtime": 0,
       "skipped": ["docker volumes (not scanned in v0.1)", "spill/"]}
    ]}
  }
}
```

`newest_mtime` is an integer (epoch seconds), matching the size + int(mtime) key the
incremental skip compares on.

## Privacy invariants

- **Transcripts and anything derived from them never enter a git repo.** The cache root and
  its contents stay on device; never commit them.
- **Worktree guard:** the script aborts if the resolved cache root's nearest existing
  ancestor is inside a git worktree (`git rev-parse --is-inside-work-tree`).
- **Sources are read-only:** files are copied out; pi's own session directories are never
  written to or pruned.
- Fixtures in this repo are synthetic; real transcript text is never copied into it.

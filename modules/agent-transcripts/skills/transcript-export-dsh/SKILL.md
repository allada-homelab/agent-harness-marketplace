---
name: transcript-export-dsh
description: Export dsh (DeepSeek harness) zstd session logs from the host DSH_HOME and dev-container docker volumes into the on-device agent-transcripts cache. Use when the user wants to "export dsh transcripts" or "collect deepseek sessions". Read-only, incremental, never writes into a git repo.
tags: [observability]
---

# transcript-export-dsh

Copies dsh session logs from every place they live on this machine into the shared on-device
agent-transcripts cache, so they can be indexed and analyzed without touching the originals.
Files stay zstd-compressed exactly as dsh wrote them; the ingest step decodes them.

**Read-only, incremental.** Sources are never mutated (docker volumes are mounted `:ro`);
nothing is written into a git worktree; a re-run copies only files whose size or integer
mtime changed.

## What it discovers (three tiers, deduped by volume name)

1. **Host** — the `sessions/` directory under dsh's home (`$DSH_HOME` when set, else the
   `.dsh` directory in the user's home).
2. **Container mounts** — `docker ps -a` then `docker inspect`, taking any mount whose
   destination ends in `/.dsh` (running or stopped containers, any volume name).
3. **Name-pattern sweep** — orphaned volumes whose name contains `deepseek`, for containers
   that were already deleted.

Docker missing or erroring is not fatal: it warns and exports the host source only.

## The commands

```bash
# Always dry-run first — lists each source and the file count it would copy, writes nothing.
uv run --script ../transcript-ingest/transcripts.py export dsh --dry-run

# Then the real export.
uv run --script ../transcript-ingest/transcripts.py export dsh
```

Options: `--dest DIR` (override the cache root), `--json` (also print the manifest to
stdout). After exporting, build the index with the `transcript-ingest` skill.

## Output layout

The cache root is `--dest`, else `$AGENT_TRANSCRIPT_DIR`, else an `agent-transcripts`
directory inside the user's cache directory. Under it:

```
raw/dsh/host/sessions/<cwd-key>/<session-id>/session.jsonl.zstd
raw/dsh/<volume-name>/sessions/<cwd-key>/<session-id>/session.jsonl.zstd
manifest.json
```

`manifest.json` is merged per run and keyed by harness, so exporting dsh leaves the claude
and pi entries untouched:

```json
{
  "exported_at": "<iso8601 UTC>",
  "harnesses": {
    "dsh": {"sources": [
      {"name": "host", "kind": "host|volume", "origin": "...", "subdir": "sessions",
       "files": 0, "bytes": 0, "newest_mtime": 0,
       "skipped": ["attachments/", "spill/"]}
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
- **Sources are read-only:** volume extraction runs a throwaway `alpine` container with the
  volume mounted `:ro` and streams a `tar` of `sessions/`; no exec into work containers.
- Fixtures in this repo are synthetic; real transcript text is never copied into it.

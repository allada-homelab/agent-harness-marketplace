---
name: claude-transcript-export
description: Export Claude Code transcript JSONL out of the host and dev-container docker volumes to an on-device cache for later analysis. Use when the user wants to "export claude transcripts", "copy transcripts out of dev containers", or "collect chat histories for analysis". Read-only, on-device, incremental — never mutates sources and never writes into a git repo.
context: fork
background: false
harness: [claude]
---

# claude-transcript-export

Collects Claude Code transcript JSONL from every place it lives on this machine into one
on-device root, so it can be analyzed without touching the originals.

**Read-only, on-device, incremental.** Sources are never mutated (docker volumes are mounted
`:ro`); nothing is written into a git worktree; a re-run copies only files whose size or mtime
changed.

## What it discovers (three tiers, deduped by volume name)

1. **Host** — `${CLAUDE_CONFIG_DIR:-~/.claude}/projects/`.
2. **Container mounts** — `docker ps -a` → `docker inspect`, taking any mount whose destination
   ends in `/.claude` (running or stopped containers, any volume name).
3. **Name-pattern sweep** — orphaned volumes matching `claude-code-config-*` or `*-claude-*`,
   for containers that were already deleted.

Docker missing or erroring is not fatal: it warns and exports the host source only.

## The one command

```bash
# Always dry-run first — lists each source and the file count it would copy, writes nothing.
./export.py --dry-run

# Then the real export.
./export.py

# Options: --dest DIR (override output root), --json (also print the manifest to stdout).
```

## Output layout

```
~/.cache/claude-transcripts/          # override with $CLAUDE_TRANSCRIPT_DIR
  host/projects/<slug>/*.jsonl
  <volume-name>/projects/<slug>/*.jsonl
  manifest.json
```

`manifest.json` is merged/overwritten per run:

```json
{
  "exported_at": "<iso8601 UTC>",
  "sources": [
    {"name": "...", "kind": "host|volume", "origin": "...",
     "files": 0, "bytes": 0, "newest_mtime": 0}
  ]
}
```

`newest_mtime` is an integer (epoch seconds), matching the size+int(mtime) key the incremental
skip compares on — downstream analyzers should treat it as an int.

## Privacy invariants

- **Transcripts and anything derived from them never enter a git repo.** The output root and its
  contents stay on device; do not commit anything under `~/.cache/claude-transcripts`.
- **Worktree guard:** the script aborts if the resolved output root's nearest existing ancestor
  is inside a git worktree (`git rev-parse --is-inside-work-tree`).
- **Sources are read-only:** volume extraction runs a throwaway `alpine` container with the volume
  mounted `:ro` and streams a `tar` of `projects/`; no exec into work containers.

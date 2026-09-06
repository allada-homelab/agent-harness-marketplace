# claude-transcripts

Export Claude Code transcripts out of dev containers and analyze hook fire rates, CLAUDE.md
adherence and tool-use patterns. Ships two skills:

- `claude-transcript-export` — read-only, on-device, incremental export of transcript JSONL from
  the host and dev-container docker volumes into one cache root.
- `claude-transcript-analyze` — turns an export root into a deterministic metadata index, per-turn
  flags, and an aggregate report, with bounded excerpts only where judgment is required.

Both are claude-only (`context: fork`, `harness: [claude]`). `claude-transcript-analyze`'s
`hooks` lens reuses the regexes/`analyze()` from two Claude Code hooks — `verify-claims.py` and
`reflect-on-done.py` — rather than re-implementing them, and imports them at `${CLAUDE_CONFIG_DIR:-~/.claude}/hooks/`.
If those hooks are not installed, the `hooks` lens is skipped with one stderr line and the
other lenses still run; it works fully only when your Claude Code setup ships equivalent hooks under those filenames.
`test/test_transcript_analyze.py` exercises this lens against minimal stand-in hooks under
`test/fixtures/hooks/`, not the real (private) ones.

## Install

- Claude Code: `/plugin marketplace add allada-homelab/agent-harness-marketplace` then
  `/plugin install claude-transcripts@agent-harness-marketplace`

This module is Claude-only.

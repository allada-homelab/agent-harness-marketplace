# agent-transcripts — design

Date: 2026-09-13. Status: approved (design reviewed in session before this file was written).

## Goal

One module, `modules/agent-transcripts/`, that exports chat transcripts from every supported
agent harness (Claude Code, pi, dsh) into an on-device cache as raw, byte-for-byte copies, and
builds a derived, rebuildable sqlite index over them so later analysis can query one schema
instead of re-parsing three formats. `modules/claude-transcripts/` stays untouched for
backwards compatibility.

## Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Canonical store | Raw files; sqlite is derived and rebuildable | A parser bug or schema change must never require re-exporting sources that may be gone (deleted dev-container volumes). |
| Skill scope | Portable (no `harness:`, no `context: fork`) | Export and ingest are "run this script"; a pi user should export pi transcripts from pi. |
| Code layout | One Python script in the ingest skill; the three export skills reference it via `../transcript-ingest/transcripts.py` | The shared part (dest resolution, worktree guard, incremental copy, manifest merge, docker-volume extraction) is ~150 lines; three copies would drift. `lib/` and `extensions/` stay forbidden — that ban is about harness-loaded code, which this is not. |
| Lint extension | `bin/lint-skills.py` resolves `../` asset paths too and requires them to exist inside the same module | Closes the gap that made cross-skill references risky. |
| Module name | `agent-transcripts` | Matches the repo's vocabulary. |
| zstd | `zstandard` as a PEP 723 inline dependency; `bin/check.sh`'s pytest line gains `--with zstandard` | The gate pins Python 3.12, so the 3.14 stdlib module is out; a host `zstd` binary is a silent dependency. |

## Module layout

```
modules/agent-transcripts/
  package.json                       # version 0.1.0; pi.skills ["skills/*"]; dsh.bundle.patch
  .claude-plugin/plugin.json         # same version
  cordis.patch.yml                   # empty content-module patch (copy the documented stub)
  README.md
  skills/transcript-export-claude/SKILL.md
  skills/transcript-export-pi/SKILL.md
  skills/transcript-export-dsh/SKILL.md
  skills/transcript-ingest/SKILL.md
  skills/transcript-ingest/transcripts.py     # the only code; uv script, PEP 723 header
  test/test_export.py
  test/test_ingest.py
  test/fixtures/{claude,pi,dsh}/...           # synthetic, never copied transcript text
```

Repo edits outside the module: `.claude-plugin/marketplace.json` entry (same version,
`"source": "./modules/agent-transcripts"`), `modules/index.yaml` regenerated, the lint
extension, the `check.sh` pytest line. The root `package.json` `pi.skills` is untouched
(all four skills are portable).

## Commands

```
transcripts.py export claude|pi|dsh [--dry-run] [--dest DIR] [--json]
transcripts.py ingest [--dest DIR] [--rebuild]
transcripts.py stats  [--dest DIR]
```

Run with `uv run --script transcripts.py …`. Exit code non-zero on any error, including a
parse failure of a single file (which is recorded and does not stop the run).

## Export layer

**Root:** `--dest` > `$AGENT_TRANSCRIPT_DIR` > `<user cache dir>/agent-transcripts`
(`XDG_CACHE_HOME` or `~/.cache`). The resolved root is refused if its nearest existing
ancestor is inside a git worktree, exactly as `claude-transcripts` does.

**Layout under the root:**

```
raw/claude/<source>/projects/<slug>/<session>.jsonl
raw/claude/<source>/projects/<slug>/<session>/subagents/*.jsonl and *.meta.json
raw/claude/<source>/projects/<slug>/<session>/tool-results/*.txt
raw/pi/<source>/<root-tag>/<ts>_<uuid>.jsonl
raw/dsh/<source>/sessions/<cwd-key>/<session-id>/session.jsonl.zstd
manifest.json
transcripts.db
```

`<source>` is `host` or a docker volume name. `<root-tag>` for pi is `settings` (the
`sessionDir` from pi's settings.json or `$PI_CODING_AGENT_SESSION_DIR`) or `default`
(`$PI_CODING_AGENT_DIR` or `~/.pi/agent`, then `sessions/`), so files from both roots
coexist without collision.

**Discovery per harness** (all read-only; docker absent or failing is a warning, host only):

- **claude** — host `${CLAUDE_CONFIG_DIR:-~/.claude}/projects`; container mounts whose
  destination ends in `/.claude` (running or stopped); orphaned volumes matching
  `claude-code-config-*` or `*-claude-*`. Copies the whole `projects/` tree, which now
  includes per-session `subagents/` and `tool-results/` directories.
- **pi** — the settings root if `sessionDir` is set in `${PI_CODING_AGENT_DIR:-~/.pi/agent}/settings.json`
  or `$PI_CODING_AGENT_SESSION_DIR` is set; and the default root always. Flat or
  per-cwd-slug layouts are both copied as found. Docker volumes are not scanned for pi in
  v0.1 (none exist on the reference machine); the manifest says so.
- **dsh** — host `${DSH_HOME:-~/.dsh}/sessions`; container mounts whose destination ends in
  `/.dsh`; orphaned volumes matching `*deepseek*`. Copies `sessions/` only. Files stay
  zstd-compressed.

Attachments (`dsh attachments/`), spill directories (dsh `spill/`, pi's third-party
`spill/`) are **not exported** in v0.1: dsh keeps them beside `sessions/` so they are never reached, and the pi exporter skips a top-level `spill/` directory inside a session root; `manifest.json` records `"skipped": [...]` per source.

**Incremental:** a file is copied when its size or integer mtime differs from the existing
copy. Volume extraction runs a throwaway `alpine` container with the volume mounted `:ro`
and streams a tar, as `claude-transcripts` does.

**manifest.json** (merged per run; keyed by harness then source):

```json
{"exported_at": "<iso8601 UTC>",
 "harnesses": {"claude": {"sources": [{"name": "host", "kind": "host|volume", "origin": "...",
   "files": 0, "bytes": 0, "newest_mtime": 0, "skipped": []}]}, "pi": {...}, "dsh": {...}}}
```

## Ingest layer

`transcripts.db` beside `raw/`. Everything in it derives from `raw/`; `--rebuild` deletes
and recreates it. Schema (`PARSER_VERSION` is a module constant, bumped when any parser's
output changes):

```sql
files       (id, harness, relpath UNIQUE, size, mtime, parser_version, status, error, parsed_at)
sessions    (id, harness, native_id, file_id → files, cwd, project_key, kind, parent_native_id,
             started_at, ended_at, model, title)          -- kind: main | subagent
messages    (id, session_id → sessions, ord, native_id, parent_native_id, on_main_path,
             role, ts, text, model, stop_reason, input_tokens, output_tokens, raw)
             -- role: user | assistant | tool_result | system
tool_calls  (id, message_id → messages, call_id, name, arguments, result_message_id, is_error)
messages_fts  FTS5 external-content table over messages.text, kept in sync by triggers
```

A file is (re)parsed when it is new, its size or mtime changed, or its `parser_version` is
older than the constant. Re-parsing deletes that file's sessions (cascading) first. A parse
exception records `status='error'` and the message on the `files` row, the run continues,
and the exit code is non-zero at the end.

### Parser rules

**claude** — one JSONL per session plus `subagents/*.jsonl` (kind `subagent`,
`parent_native_id` = the parent session id). Conversation records are `type` in
`user`/`assistant`; everything else (`system`, `attachment`, `mode`, `ai-title`, …) is
skipped except `ai-title`, which fills `sessions.title`. Tree via `uuid`/`parentUuid`.
`on_main_path` = the chain from the last conversation record up to the root. Tool calls are
`tool_use` blocks; results are `tool_result` blocks inside user records (role
`tool_result`). `cwd`, `gitBranch`, `version`, `model`, `usage` come from the records.

**pi** — header `{"type":"session","version":N,...}` gives native id, cwd, `parentSession`
(a path → kind `subagent`/fork with `parent_native_id` = that file's session id). Records
are `message` (roles `user`, `assistant`, `toolResult`), and non-message entries
(`model_change`, `thinking_level_change`, `compaction`, `custom`, `custom_message`,
`branch_summary`, `label`, `session_info`) are skipped, except `session_info.name` → title
and `model_change` → current model for following messages. Tree via `id`/`parentId`;
`on_main_path` walks from the last-appended entry. Version 2 and 3 are accepted; version 1
raises (recorded as an error).

**dsh** — decode `session.jsonl.zstd` as concatenated zstd frames with a streaming
decompressor; a truncated last frame yields whatever complete lines precede it. Header gives
native id, cwd, `parentSession`, `origin` (→ kind `subagent` when `subagent`),
`delegationDepth`. Only `user/message`, `assistant/message`, `tool/call`, `tool/result` are
used; every chunk row (`assistant/chunk`, `text-chunks`, `reasoning-chunks`,
`tool-call-chunks`) and every control row is dropped. `session/title` → title. Ordering is
`seq`; there is no intra-file tree, so `on_main_path` is always true. Token usage from
`assistant/message.data.usage`.

**All harnesses:** `text` is the concatenation of text blocks only (no tool arguments, no
thinking); `raw` is the original record JSON. `project_key` is the directory-derived slug
where one exists, else derived from `cwd` the same way Claude does.

## Skills

Four portable skills. Bodies contain no `~/`, no absolute paths, no `CLAUDE_*` placeholders,
no bang-backtick. Each export skill: what it discovers, the one command
(`uv run --script ../transcript-ingest/transcripts.py export <harness> --dry-run` first, then
without), the output layout, and the privacy invariants. The ingest skill: the schema
summary, the three commands, and the rule that the db is derived and safe to delete.

Privacy invariants (all four skills): transcripts and anything derived from them never enter
a git repo; the worktree guard enforces it; sources are never mutated; fixtures in the repo
are synthetic.

## Testing

`pytest` under `modules/agent-transcripts/test`, run by `bin/check.sh` with
`--with zstandard`. Fixtures are hand-written from the format skeletons, never copied.

- export: worktree guard; dest resolution precedence; docker discovery from mocked
  `docker ps`/`docker inspect` output for claude and dsh; pi root discovery from a fake
  settings.json; incremental skip on unchanged size+mtime; manifest merge.
- ingest, per harness: sessions/messages/tool_calls row counts and key fields from the
  fixture; `on_main_path` marks the right chain for a branched pi fixture; dsh chunk rows
  are dropped and a truncated zstd tail still yields the complete prefix; a v1 pi header
  records an error row and the run exits non-zero.
- ingest, general: running twice is a no-op; touching a file re-parses only that file;
  `--rebuild` starts clean; FTS returns a message by a word in its text.

Gate: `CHECK_BASE=origin/main bin/check.sh` green, plus a manual run of all three exports
and an ingest on the reference machine, reported with `stats` output.

## Out of scope (v0.1)

The analyze skill (will query the db later instead of re-parsing); attachments and spill
content; dsh's own `query.sqlite`; backfill from the old `claude-transcripts` cache root;
pi docker volumes.

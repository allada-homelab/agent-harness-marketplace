---
name: claude-transcript-analyze
description: Analyze exported Claude Code transcripts for hook fire rates, CLAUDE.md adherence, and tool-use patterns — without ever loading raw transcript prose into context. Use when the user wants to "analyze claude transcripts", measure "hook fire rates", audit "CLAUDE.md adherence", or study "tool use patterns". Deterministic index + aggregates on device; bounded excerpts + cheap-subagent labeling only where judgment is required.
context: fork
background: false
harness: [claude]
---

# claude-transcript-analyze

Turns an export root (from the `claude-transcript-export` skill, or a live `~/.claude`
projects dir laid out the same way) into a deterministic metadata index, per-turn flags,
and an aggregate report — so hooks and CLAUDE.md adherence can be measured with evidence,
never guessed. Feeds the hook audit.

Input layout (one row per turn indexed):

```
<root>/<source>/projects/<slug>/*.jsonl     # <source> = "host" or a docker volume name
```

## The two-layer contract (non-negotiable)

`context: fork` in the frontmatter makes the first sentence below structural rather than
disciplinary: this skill runs in its own subagent, so raw prose cannot reach the main
conversation even by mistake. `background: false` keeps the caller waiting for the result
instead of receiving it as a notification. Forks can still spawn subagents (spawn depth
limit is 3), so the Layer-2 labeling protocol below still works from inside the fork.

**The orchestrating session never opens a raw `*.jsonl` transcript.** Everything flows
through exactly three narrow channels, each free of bulk prose:

- **Layer 1 — deterministic metadata (no LLM, no prose).** `analyze.py index <root>` writes:
  - `index.jsonl` — one row per turn: session id, turn number, timestamp, tool names + counts,
    Bash failure count, edit/commit booleans, message sizes, hook-block events, and the list of
    lens rule-ids that flagged the turn.
  - `flags.jsonl` — one row per flagged turn: `flag_id` (`session:turn:rule`), rule, a short
    `match`, and a **line-range pointer** `(file, line_start, line_end)` into the source — never
    the content. At most **one flag per (rule, turn)**, so `flag_id` is a stable excerpt key.
  - `report.md` — **aggregates only**: flag counts + rates per source × rule, hook fires-vs-would-fires
    by ISO week, and the top-10 flagged sessions by id. No message content, no match strings, no paths.
- **Layer 2 — bounded excerpts (LLM only where judgment is required).**
  `analyze.py excerpt <out_dir> <flag_id>` resolves one flag pointer to a bounded excerpt:
  ±2 messages of context, each message's prose capped at ~2k chars, tool results elided to
  name/error. This is the *only* way transcript prose reaches a model, and only one flagged
  turn at a time.

The orchestrator reads index rows, report aggregates, and subagent verdict tables — and, only
for a row it must personally adjudicate, a single bounded excerpt. It never reads whole
transcripts, never batches raw prose into its own context.

## Commands

```bash
# Layer 1: build index.jsonl + flags.jsonl + report.md (output MUST be outside any git repo)
./analyze.py index ~/.cache/claude-transcripts --out ~/.cache/claude-transcripts/analysis

# Layer 2: one bounded excerpt for a single flag (the only path prose takes to a model)
./analyze.py excerpt ~/.cache/claude-transcripts/analysis <session:turn:rule>

# Re-aggregate report.md from an existing index.jsonl (no re-parse)
./analyze.py report ~/.cache/claude-transcripts/analysis
```

## Rule ids (v1 lenses, all deterministic)

- **hooks** (`lens_hooks_replay`) — actual fires from recorded Stop blocks + would-fires by
  replaying the repo's own hook `analyze()` over each turn (never re-implemented):
  - `hooks.verify_claims_fired`, `hooks.reflect_fired` — a real Stop block landed this turn.
  - `hooks.verify_claims_would_fire`, `hooks.reflect_would_fire` — the hook *would* block this
    turn (captures pre-deployment history as would-fire data). Excludes turns the user
    interrupted before Stop — no Stop event ever occurred there, so the hook could not have
    fired. Counts from before 2026-07-27 include those turns: on the 2645-turn Jul-27 corpus
    that was `reflect_would_fire` 257 vs 245 now, `verify_claims_would_fire` unchanged at 23.
- **claude-md** (`lens_claude_md`) — mechanically checkable CLAUDE.md rules only:
  - `claude_md.claim_with_tools` — a verification claim (verify-claims' own `CLAIM_RE`) with ≥1
    tool call this turn (the superset the hook lets through; for miss estimation). Unlike the
    `hooks.*_would_fire` rules above, this is *not* interrupt-filtered — it counts claims made,
    not blocks that would have landed.
  - `claude_md.blanket_git_add` — `git add -A` / `--all` / `.` (the "stage only what you changed" rule).
  - `claude_md.force_push` — `git push --force` without `--force-with-lease`.

## Labeling protocol (Layer 2, for TP/FP judgment)

A flag is a *candidate*, not a verdict — deciding true-positive vs false-positive needs judgment.
The orchestrator drives it, never the raw transcript:

1. **Batch** flagged turns into groups of **~10 excerpts per subagent** (resolve each via
   `analyze.py excerpt`). Give each subagent only its 10 excerpts + the rubric below.
2. **Fixed TP/FP rubric** (identical for every subagent, every batch):
   - **TP** — the flag correctly identifies the behavior the rule targets (e.g. a genuine
     unsupported verification claim; a real blanket `git add`; a work-closing turn that truly
     lacks a status line).
   - **FP** — the pattern matched but the behavior is fine in context (e.g. the "claim" quotes
     the rule text itself; `--force` inside a string literal, not an executed push; a status
     line present in a form the regex missed).
3. **Model tier by stakes** (per the delegation rules): bulk TP/FP classification → **cheapest
   tier** (Haiku-class; optionally local-llm/pi if opted in). Ambiguous or disputed rows →
   escalate to **mid tier** (Sonnet-class). Reserve the orchestrator's own reads for rows it
   must personally adjudicate.
4. **Verdict table** — each subagent returns one row per flag, and nothing else:

   | flag_id | verdict | reason |
   |---|---|---|
   | `<session:turn:rule>` | `TP` \| `FP` | one line — why |

   The orchestrator consumes only these tables (plus aggregates) to reach per-rule / per-hook
   FP rates and the keep/fix/drop verdicts.

## Privacy invariants (hard rules)

- **Transcripts and anything derived from them never enter a git repo** and stay on device.
  `analyze.py index` **aborts** if the resolved `--out` dir is inside a git worktree
  (`git rev-parse --is-inside-work-tree`). Default output root: `~/.cache/claude-transcripts/`
  (override via `$CLAUDE_TRANSCRIPT_DIR`).
- **`report.md` carries aggregates only** — counts, rates, ISO weeks, session ids. Never message
  content, never `match` strings, never file paths.
- **`flags.jsonl` pointers are line ranges, not content**; a short `match` snippet lives there
  (on device) purely as the excerpt lookup aid — it is never promoted into the report or a repo.
- **Committed test fixtures are synthetic reconstructions** — same JSONL structure and trigger
  pattern as observed cases, all content rewritten. Never copied transcript text.

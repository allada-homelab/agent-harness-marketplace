---
name: ingest
description: Bootstrap or grow this repo's .wiki/ from its history — fix and revert commits, PR descriptions, docs and runbooks, and existing OKF or llm-wiki bundles — by fanning out okf-wiki explorer agents and landing the concepts that pass the capture bar. Use when the wiki is empty, when the digest says "run ingest", or when the user asks to "seed", "bootstrap", "ingest" or "migrate" a wiki.
user-invocable: true
argument-hint: "[--fanout N] [--max N] [--since <date>] [<existing bundle dir to migrate>]"
---

# ingest

Arguments, if any: $ARGUMENTS (on some harnesses they arrive as text after this skill
instead). Read `../wiki/SKILL.md` first. Let `<okf>` be the absolute path of `../wiki/okf.py`.

## 1. Migrate existing bundles first

If the arguments name a directory, or the repo has an `llm-wiki/` or other OKF bundle:

1. `python3 <okf> migrate <dir> --dry-run` and show the user the summary line.
2. On a yes, run it without `--dry-run`. Report every `NEEDS REVIEW` and `SKIPPED` line: a
   NEEDS REVIEW concept has a type the closed set lacks, so pick one of the six and edit it;
   a SKIPPED one has frontmatter outside the supported YAML subset, so fix the source file
   and migrate again.

## 2. Slice the history

Build independent slices, each small enough for one explorer:

- fix, revert and hotfix commits: `git log --format='%h %ad %s' --date=short -i
  --grep='fix\|revert\|hotfix\|workaround'` (plus `--since` if given), split into date
  windows of about 40 commits;
- merged PR descriptions, when `gh` works: `gh pr list --state merged --limit 200 --json
  number,title,body,url`, split by 40;
- `docs/` and runbook files that hold warnings or gotchas, split by directory. Skip
  `CLAUDE.md`, `AGENTS.md` and other always-loaded files: capture bar rule 4.

## 3. Fan out

`python3 <okf> fanout [--fanout N]` gives the width. Dispatch one `okf-wiki:explorer` per
slice, at most that many in flight, each with: the slice (the exact command or file list),
`okf: <okf>`, and the current concept ids from `.wiki/index.md` so it proposes updates
instead of duplicates.

## 4. Land

Explorers return proposed briefs. Merge duplicates across explorers, apply the capture bar
yourself, and drop anything weak; fewer strong concepts beat many thin ones. Keep at most
`--max N` (default 15), strongest first: a flood of thin concepts pushes the session digest
into titles-only mode. Show the user the list (type, id, one-line claim) and land it on a
yes, dropping any they strike. Hand the survivors to scribes exactly as the capture skill does (one concept per scribe, at most the
fan-out width in flight). Finish with one summary receipt, `wiki: +<n> concepts (ingest)`,
followed by the per-concept receipt lines.

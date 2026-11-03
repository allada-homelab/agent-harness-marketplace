---
name: uv-rules-sweep
description: Rebuilds the uv-best-practices UVP rule set from uv's own docs at a pinned release. Clones astral-sh/uv at the tag, runs a multi-agent workflow that extracts checkable practices from every docs page with quotes, judges them per reference topic, live-checks behavioral claims on that uv release, and writes a ledger of keep, update, new and reject verdicts with coverage. Use when asked to sweep, rebuild or re-derive the uv rules against a uv version.
argument-hint: "[uv tag, default: latest release]"
user-invocable: true
disable-model-invocation: true
---

# uv rules sweep

Rebuild the UVP rules in the `best-practices` module from the uv source at one
release. Target tag: $ARGUMENTS — when none is given, the latest release from
`gh release view -R astral-sh/uv --json tagName -q .tagName`. uv tags have no
`v` prefix (`0.13.7`).

The sweep produces a ledger. It never edits a rule: applying the ledger is a
separate, reviewed step (the last section below).

## 1. Preconditions

Run from a checkout of agent-harness-marketplace: the rules live at
`modules/best-practices/skills/uv-best-practices/` under its root, and the
sweep needs that absolute path. Stop if it is not there.

## 2. Pin the source

Make a new, empty directory under your scratch directory, then clone into it:

```
git clone -q --filter=blob:none --branch <tag> https://github.com/astral-sh/uv <dir>/uv
git -C <dir>/uv rev-parse HEAD
```

Keep the full history (no `--depth`): the verify stage reads other tags'
`uv.schema.json` to find when a setting key appeared. Record the tag and the
commit. The clone is untrusted data: read it, never run code from it.

## 3. Shard the docs

Run [`./scripts/shards.py`](./scripts/shards.py), resolved against this
skill's directory:

```
python3 -I <skill dir>/scripts/shards.py <dir>/uv > <dir>/shards.json
```

It prints the docs pages (excluding `docs/pip/`) packed into shards of about
1800 lines, plus `uv.schema.json` as its own shard. Check the exit code. The
topics are the stems of the files in the rule set's `references/` directory.

## 4. Run the workflow

The workflow is `workflows/uv-rules-sweep.workflow.js` at this module's root
(two directories above this skill). Pass `args` as a JSON object, not a string:

- **Claude Code**: the Workflow tool, with `scriptPath` set to that file's
  absolute path.
- **pi and dsh**: the `run_workflow` tool, with
  `workflow: "best-practices-maintainer:uv-rules-sweep"`. Every child there runs
  on the fleet's large model: the bridges route the `sonnet` and `opus` aliases
  to it.
- **Neither tool**: stop and say so. The sweep is about 23 agents of work, too
  much to do inline.

```json
{
  "repo": "<dir>/uv",
  "tag": "<tag>",
  "sha": "<commit>",
  "shards": <contents of shards.json>,
  "topics": ["<reference file stem>", "…"],
  "rulesDir": "<repo root>/modules/best-practices/skills/uv-best-practices",
  "outDir": "<dir>/out"
}
```

A run has one extractor per shard, one judge per topic, up to four
live-checkers shared across topics, and one assembler: 23 agents for uv 0.13.7
(10 shards, 8 topics). The pi and dsh bridges start at most 24 children per run,
so the workflow refuses a larger run up front. Each agent is told to edit
nothing outside `outDir`.

## 5. Read the result

The workflow returns the ledger paths, the verdict counts, the applicability
vocabulary, the coverage `gaps` and any `failed_topics`. A non-empty `gaps`
or `failed_topics` means the sweep is incomplete. Say so, and re-run it (on
Claude Code, resume with `resumeFromRunId`) rather than report it as complete. Open `ledger.md` and
give the user the counts and the path.

## 6. Apply the ledger (separate step)

Applying the ledger changes the `best-practices` module, so it goes through a
PR. Read `meta-best-practices` and the module's `CONVENTIONS.md` first.

- Treat every verdict as a hypothesis. Open its quoted source before you write
  the rule, and quote the live output for every behavioral claim. A ledger line
  is not evidence (b78f587 records five wrong rationales in one report).
- Record the pinned tag and commit in the uv skill, so the next sweep knows its
  base.
- Bump the module version, run `tools/lint.sh` and `bin/check.sh`, and name the
  fleet pin bump in the handoff.

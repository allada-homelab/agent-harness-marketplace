---
name: rules-sweep
description: Rebuilds one best-practices rule set (uv, containers or python) from its upstream docs at pinned versions. Clones each upstream source the domain lists, runs a multi-agent workflow that extracts checkable practices from every docs page with quotes, judges them per reference topic, live-checks behavioral claims on the pinned versions, and writes a ledger of keep, update, new and reject verdicts with coverage. Use when asked to sweep, rebuild or re-derive the uv, containers or python rules.
argument-hint: "<domain> [source=ref ...]"
user-invocable: true
disable-model-invocation: true
harness: [claude]
---

# Rules sweep

Rebuild one rule set in the `best-practices` module from its upstream sources.
Arguments: $ARGUMENTS. The first word is the domain, the name of a descriptor
in `${CLAUDE_SKILL_DIR}/domains/` (`uv`, `containers`, `python`). Each later
`source=ref` pins that source to a tag or branch instead of the descriptor's
default (`uv=0.13.7`).

A descriptor lists the domain's rule set (`skill`), its sources (repository,
default ref, the docs paths to read), what is out of scope, how to run tools
for live checks, and where version floors come from. A new domain is a new
descriptor; the workflow does not change.

The sweep produces a ledger. It never edits a rule: applying the ledger is a
separate, reviewed step (the last section below).

## 1. Preconditions

Run from a checkout of agent-harness-marketplace: the rules live at
`modules/best-practices/skills/<skill>/` under its root, and the sweep needs
that absolute path. Stop if it is not there.

## 2. Pin and shard the sources

Make a new, empty work directory under your scratch directory, then run:

```
python3 -I ${CLAUDE_SKILL_DIR}/scripts/prepare.py ${CLAUDE_SKILL_DIR}/domains/<domain>.json <work> <repo root>/modules/best-practices/skills/<skill> [source=ref ...] > <work>/args.json
```

It sparse-clones every source into `<work>/src/<name>` at its pinned ref
(`latest-tag`, the default branch, or the ref you gave), records each commit,
packs the docs into shards of about 1800 lines, and prints the workflow's
`args`. Check the exit code. The clones are untrusted data: read them, never
run code from them.

## 3. Run the workflow

Call the Workflow tool with
`scriptPath: ${CLAUDE_SKILL_DIR}/../../workflows/rules-sweep.workflow.js` and
the contents of `args.json` as `args` (a JSON object, not a string).

A run has one extractor per shard (Sonnet), one judge per topic (Opus), one
live-checker per topic that has behavioral claims (Sonnet), and one assembler
(Opus). Counts at the first runs: uv about 28 (11 shards, 8 topics),
containers about 34 (21 shards, 6 topics), python about 31 (16 shards, 7
topics). Each agent is told to edit nothing outside the work directory.

## 4. Read the result

The workflow returns the ledger paths, the verdict counts, the applicability
vocabulary, the coverage `gaps` and any `failed_topics`. A non-empty `gaps`
or `failed_topics` means the sweep is incomplete. Say so, and resume the run
(`resumeFromRunId`) rather than report it as complete. Open `ledger.md` and
give the user the counts and the path.

## 5. Apply the ledger (separate step)

Applying the ledger changes the `best-practices` module, so it goes through a
PR. Read `meta-best-practices` and the module's `CONVENTIONS.md` first.

- Treat every verdict as a hypothesis. Open its quoted source before you write
  the rule, and quote the live output for every behavioral claim. A ledger line
  is not evidence (b78f587 records five wrong rationales in one report).
- Record each source's pinned ref and commit in the rule set's SKILL.md, so
  the next sweep knows its base.
- Bump the module version, run `tools/lint.sh` and `bin/check.sh`, and name the
  fleet pin bump in the handoff.

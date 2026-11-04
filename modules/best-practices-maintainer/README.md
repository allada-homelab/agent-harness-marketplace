# best-practices-maintainer

Maintainer tooling for the [`best-practices`](../best-practices/) library. The
library ships the rules; this module rebuilds them from each tool's own docs at
a pinned release, so a rule traces to a quoted source and not to memory.

Claude Code only (`harness: [claude]`): the sweep is a Workflow script.

## `/rules-sweep <domain> [source=ref ...]`

Domains: `uv`, `containers`, `python`, one descriptor each in
`skills/rules-sweep/domains/`. A descriptor names the rule set, its upstream
sources (repository, ref, docs paths), what is out of scope, how to run the
tools for live checks, and where version floors come from.

1. `skills/rules-sweep/scripts/prepare.py` sparse-clones each source at its
   pinned ref (`latest-tag`, the default branch, or a `source=ref` override),
   records the commits, and packs the docs into shards.
2. Runs `workflows/rules-sweep.workflow.js`:
   - **Extract**: one Sonnet reader per shard. Each item carries a verbatim
     quote, `path:line`, a topic, an `applies_when` condition and a
     `behavioral` flag, and every heading read is listed for coverage.
   - **Judge**: one Opus judge per reference topic. It checks each quote,
     clusters duplicates, rules keep, update, new or reject, and reports on
     each existing rule whether the docs support it, contradict it or are
     silent.
   - **Verify**: live-runs each behavioral claim on the pinned versions and
     finds its version floor.
   - **Assemble**: one Opus agent writes `ledger.json` and `ledger.md`, with
     the applicability vocabulary (`core` plus detectable tags) and the
     `Requires.` floors.
3. Returns the ledger. It edits no rule: applying the ledger is a reviewed PR
   against `best-practices`.

## Install

Claude Code: `/plugin install best-practices-maintainer@agent-harness-marketplace`.

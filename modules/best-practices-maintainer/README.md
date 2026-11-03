# best-practices-maintainer

Maintainer tooling for the [`best-practices`](../best-practices/) library. The
library ships the rules; this module rebuilds them from each tool's own docs at
a pinned release, so a rule traces to a quoted source and not to memory.

Claude Code only (`harness: [claude]`): the sweep is a Workflow script.

## `/uv-rules-sweep [tag]`

1. Clones `astral-sh/uv` at the tag (default: the latest release) and records
   the commit.
2. Splits the docs pages (excluding `docs/pip/`) and `uv.schema.json` into
   shards with `skills/uv-rules-sweep/scripts/shards.py`.
3. Runs `workflows/uv-rules-sweep.workflow.js`:
   - **Extract**: one Sonnet reader per shard. Each item carries a verbatim
     quote, `path:line`, a topic, an `applies_when` condition and a
     `behavioral` flag, and every heading read is listed for coverage.
   - **Judge**: one Opus judge per reference topic. It checks each quote,
     clusters duplicates, rules keep, update, new or reject, and reports on
     each existing rule whether the docs support it, contradict it or are
     silent.
   - **Verify**: live-runs each behavioral claim with `uvx --from uv==<tag> uv`
     and finds its version floor from the changelogs and the schema history.
   - **Assemble**: one Opus agent writes `ledger.json` and `ledger.md`, with
     the applicability vocabulary (`core` plus detectable tags) and the
     `Requires.` floors.
4. Returns the ledger. It edits no rule: applying the ledger is a reviewed PR
   against `best-practices`.

## Install

Claude Code: `/plugin install best-practices-maintainer@agent-harness-marketplace`.

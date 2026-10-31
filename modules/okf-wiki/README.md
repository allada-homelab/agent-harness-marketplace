# okf-wiki

A per-repo wiki for agents at `<repo>/.wiki/`, in Open Knowledge Format v0.2. It holds what
the code cannot tell you (gotchas, decisions, runbooks, conventions, architecture, external
references), keeps itself honest with grep-only Verify anchors checked against git, and
learns in the background on cheap models.

- **Read:** a SessionStart hook injects a compact digest (fresh concepts with their
  claim-style descriptions first, stale ones marked ⚠). The `recall` skill answers deeper
  questions inline: it greps `.wiki/index.md`, reads the hits and cites `concept:<id>`.
- **Write:** the injected rule and a Stop-hook nudge (at most once per branch per session,
  when the session's own commits or edits change more than `.wiki/` or version pins — not
  for a pull or a merge of the default branch) prompt the agent to `capture` durable
  findings; concepts the work made stale wait for the next digest's ⚠. A cheap `scribe`
  agent writes them and the agent prints a receipt (`wiki: +gotcha/<id>`). When the user
  standing-approves wiki-only PRs, a background `lander` agent watches each one with
  `pr-flow -C <worktree> watch --merge-if-only .wiki/` and merges it when green.
- **Heal:** a concept whose anchor failed, or whose anchored text changed since its verified
  commit, is STALE (⚠); the scribe re-verifies, fixes or deprecates it. One whose anchor file
  changed while its anchors still pass is TOUCHED, not ⚠.
- **Grow and prune:** `ingest` mines fix commits, PRs, docs and existing bundles with
  parallel `explorer` agents; `tend` reports health; `reflect` scores whether the wiki helps
  (from the agent-transcripts index and git) and proposes fixes.

Everything deterministic is one stdlib script, `skills/wiki/okf.py`: `validate`, `index`,
`digest`, `new`, `stamp`, `fresh`, `anchor`, `mv`, `tags`, `retag`, `migrate`, `fanout`, `stats` and the two
hook entry points. The final stdout line is always `okf: <verb> <verdict> [detail]`. Exit
codes: 0 ok · 1 findings · 2 refusal · 3 near-duplicate (`new`).

Parallel work (ingest explorers, heal and capture scribes, reflect auditors) runs at most
`--fanout N`, else `OKF_WIKI_FANOUT`, else 4 subagents at once; pi's bridge caps it at 4.
`OKF_WIKI_NUDGE=off` silences the Stop hook's nudges on a machine; the digest stays on.

## Model tiers on pi and dsh

The agents pin Claude aliases (`haiku`, `sonnet`) for cost. On pi and dsh a child inherits the
session model unless the harness maps the alias, so the cheap tier holds only where an alias
map exists.

Design: `docs/superpowers/specs/2026-09-25-okf-wiki-design.md`.

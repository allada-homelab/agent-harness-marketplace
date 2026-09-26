# okf-wiki

A per-repo wiki for agents at `<repo>/.wiki/`, in Open Knowledge Format v0.2. It holds what
the code cannot tell you (gotchas, decisions, runbooks, conventions, architecture, external
references), keeps itself honest with grep-only Verify anchors checked against git, and
learns in the background on cheap models.

- **Read:** a SessionStart hook injects a compact digest of every concept (claim-style
  descriptions, stale ones marked ⚠). The `recall` skill sends deeper questions to a cheap
  `reader` agent that answers with `concept:<id>` citations.
- **Write:** the injected rule and a Stop-hook nudge (on a new commit, or once per session
  while the tree is dirty) prompt the agent to `capture` durable findings; a cheap `scribe`
  agent writes them and the agent prints a receipt (`wiki: +gotcha/<id>`).
- **Heal:** a concept whose anchor files changed since its verified commit is STALE; the
  scribe re-verifies, fixes or deprecates it.
- **Grow and prune:** `ingest` mines fix commits, PRs, docs and existing bundles with
  parallel `explorer` agents; `tend` reports health; `reflect` scores whether the wiki helps
  (from the agent-transcripts index and git) and proposes fixes.

Everything deterministic is one stdlib script, `skills/wiki/okf.py`: `validate`, `index`,
`digest`, `new`, `stamp`, `fresh`, `anchor`, `mv`, `migrate`, `fanout`, `stats` and the two
hook entry points. The final stdout line is always `okf: <verb> <verdict> [detail]`. Exit
codes: 0 ok · 1 findings · 2 refusal · 3 near-duplicate (`new`).

Parallel work (ingest explorers, heal and capture scribes, reflect auditors) runs at most
`--fanout N`, else `OKF_WIKI_FANOUT`, else 4 subagents at once; pi's bridge caps it at 4.
`OKF_WIKI_NUDGE=off` silences the Stop hook's nudges on a machine; the digest stays on.

Design: `docs/superpowers/specs/2026-09-25-okf-wiki-design.md`.

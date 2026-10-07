# artifacts

Local HTML artifacts for pi and dsh. One skill (`artifacts`) carries Claude Code's artifact
craft — design, dataviz, diagramming — rewritten for a self-contained file with no hosting,
plus `artifactctl.py` (`prepare | check | open`, stdlib). Viewing is each harness's own:
dsh's `present` tool → Document Preview (scripts run with *Coding Tools* on); pi opens the
system browser or prints the path.

Off on Claude Code by default: Claude ships `artifact-design`, `artifact-diagramming`,
`dataviz` and `artifact-capabilities` built in, with a hosted Artifact tool.

## Provenance and re-sync

`references/` is a port of Claude Code **2.1.292**'s bundled skills (2026-10-07). The bodies
are not on disk — they live in the binary's lazy chunks and two are assembled per session — so
the only reader is the Skill tool. To re-sync: in a Claude Code session load `artifact-design`,
`artifact-diagramming`, `dataviz`, `artifact-capabilities`; dump each verbatim; `diff` against
`references/dataviz/README.md`, `references/diagramming.md`, and the body half of
`references/design.md`; re-apply the *Local page contract* rewrite (the edits are listed in
dotfiles `docs/superpowers/plans/2026-10-07-local-artifacts-module.md`, Task 3).

## Phase 2

`references/runtime-seam.md` specifies `window.artifact`; nothing here implements it.

# REA

Reverse Engineer Anything — decompile and analyze compiled binaries through the
published `ghcr.io/allada-homelab/rea` container (REA 6.8.0 + Ghidra 12.1.4
headless + full JDK 25).

This module is a **skill** for the pi and dsh harnesses only. It teaches the
agent to drive the REA container directly with `docker run` (mounting the target
directory at `/analysis`), because a committed `mcp.json` is not viable here:

- a **stdio** server would be spawned by the harness proxy with an empty `cwd`,
  so a `$PWD` bind mount would not reach the agent's session directory;
- a **streamable-http** server would need an `https` non-loopback URL, and the
  homelab REA endpoint cannot be committed (the repo forbids private/RFC1918
  paths and hostnames in publishable content).

So the skill is structured as a process, not a command dump: `skills/rea/SKILL.md`
is the thin entrypoint (identify the target type, inventory, baseline,
reconstruct, verify, record) with per-type depth in `references/` — native
Ghidra (`native-ghidra.md`), Python bytecode (`python-bytecode.md`), Go
(`go-binaries.md`), JS/Electron (`js-electron.md`), and the cross-cutting
provenance/verification rules (`workflow.md`). A module
`agents/python-module-reconstructor.md` carries the reconstruction brief once,
so a decompile project fans out to workers without re-writing the prompt. See
`skills/rea/SKILL.md` for the entrypoint.

Not for Claude Code: this module ships no `.claude-plugin/plugin.json` and no
marketplace entry.

## Install

pi and dsh install modules at a git tag. The fleet pin is
`agents/modules.tsv` in the maintainer's dotfiles repo; adding this module there
(and bumping the marketplace `ref`) is the paired change that makes it live.

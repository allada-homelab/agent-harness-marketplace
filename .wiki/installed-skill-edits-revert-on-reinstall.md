---
type: gotcha
title: Installed skill edits revert on reinstall — edit the marketplace source, not the installed copy
description: "Editing ~/.dsh/profiles/web/node_modules/@allada-homelab/<m>/skills/<s>/SKILL.md is ephemeral: a reinstall re-creates it from modules/<m>/ in agent-harness-marketplace."
tags: [skills, modules, dsh, fleet]
generated: {by: okf-wiki/unknown, at: 2026-11-03T17:29:22Z}
verified:
  - {by: okf-wiki/unknown, at: 2026-11-03T17:29:22Z, commit: c280ad7f53fc}
sources:
  - {id: session-edit, resource: "dsh session 2026-11-03: edited installed rea SKILL.md 84→130 lines (Python-bytecode section), reported 'rea skill updated'"}
  - {id: installed-copy, resource: "diff 2026-11-03: ~/.dsh/profiles/web/node_modules/@allada-homelab/rea/skills/rea/SKILL.md is byte-identical to origin/main:modules/rea/skills/rea/SKILL.md (84 lines)"}
  - {id: claude-md, resource: "CLAUDE.md in agent-harness-marketplace: 'Pairing with the fleet' plus generated-manifest and version-bump rules"}
---

# Installed skill edits revert on reinstall — edit the marketplace source, not the installed copy

## Symptom

A dsh session edited `/home/davidallada/.dsh/profiles/web/node_modules/@allada-homelab/rea/skills/rea/SKILL.md` (84 → 130 lines, adding a Python-bytecode section) and reported "rea skill updated". Within two days the edit was gone: a plugin reinstall re-created the module from the marketplace repo at the pinned ref, and the installed file is byte-identical to origin/main's 84-line version.[^session-edit][^installed-copy]

## What fails

Installed copies under `~/.dsh/profiles/web/node_modules/@allada-homelab/<module>/` are generated artifacts, not sources: dsh installs each module at a git ref pinned by the fleet's `agents/modules.tsv` (CLAUDE.md → "Pairing with the fleet"), so the reinstall overwrites the whole directory with repo content at that ref.[^claude-md] An edit that never reaches the repo is silently reverted — no error, no merge, no warning. Tell: after a reinstall the installed SKILL.md is byte-identical to origin/main's; check with `diff <(git show origin/main:modules/<name>/skills/<skill>/SKILL.md) <installed-path>` — a stale installed copy means the repo was never updated.

## What works

Edit `modules/<name>/` in agent-harness-marketplace on a branch, bump the module version in `package.json` (the changed-module version-bump rule, enforced by `CHECK_BASE=origin/main bin/check.sh`), regenerate the generated manifests with `uv run --script bin/render-index.py --write` and `uv run --script bin/render-plugin-manifests.py --write`, then run `CHECK_BASE=origin/main bin/check.sh`.[^claude-md] The fleet picks the change up only after the dotfiles pin bump (pairing case 2), which is the normal path.

## Why

The marketplace repo publishes from `modules/<name>/`; every other copy is a build product of the install step. The reinstall is the only writer of the installed tree, so a manual edit is at best a cache — and the agent's "rea skill updated" message refers to the installed file only.

## Verify

- `modules/rea/skills/rea/SKILL.md` :: `name: rea`

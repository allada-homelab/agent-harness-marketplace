---
type: runbook
title: Removing a module
description: Deleting modules/<name> leaves refs the gate misses — a stale root pi exclude, smoke tests naming it, lockfile importers — so sweep them; dated records get a note, not a rewrite.
tags: [modules, removal, check-sh, pi, smoke, fleet]
generated: {by: okf-wiki/opus, at: 2026-09-26T14:22:38Z}
verified:
  - {by: okf-wiki/opus, at: 2026-09-26T14:22:38Z, commit: 6ac844bcd7e8}
sources:
  - {id: s1, resource: commit:002649c, title: Remove five modules and the references that outlived them}
  - {id: s2, resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/36, title: "PR #36"}
  - {id: s3, resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/41, title: "PR #41 fleet pairing: a removed module loses its row"}
  - {id: s4, resource: bin/check.sh, title: root pi manifest check iterates existing modules only}
---

# Removing a module

## When

Retiring any `modules/<name>/`. The `adding-a-module` skill covers only the add
direction, and `bin/check.sh` checks existing modules, so leftovers of a deleted
one mostly pass the gate silently.[^s1][^s2]

## Steps

1. `git rm -r modules/<name>`, then delete any untracked `modules/<name>/node_modules/`
   left behind — a leftover directory makes `check.sh` treat it as a module with no
   `package.json`.
2. Remove its entry from `.claude-plugin/marketplace.json` (the gate does flag an
   orphan entry).
3. Remove `"!modules/<name>/**"` from the root `package.json` `pi.skills` if present.
   **The gate does not flag this one**: the pi-manifest step loops over existing
   module directories, so an exclude for a vanished module passes forever.[^s4]
4. Regenerate: `uv run --script bin/render-index.py --write` and
   `uv run --script bin/render-plugin-manifests.py --write`; run `pnpm install` so the
   module's importer leaves `pnpm-lock.yaml`, and commit that.
5. `grep -rn '<name>'` outside `modules/`: repoint `tests/smoke/pi.sh` and
   `tests/smoke/dsh.sh` at a surviving module — the smoke job runs only in CI, never
   in `check.sh`, so a dangling smoke reference fails only after you push. Fix README
   and live docs.
6. Dated records — `docs/superpowers/specs/*`, `docs/superpowers/plans/*`, `handoff.md`
   — describe the repo as of their date: add a `> **Historical record — do not update.**`
   note naming what changed instead of rewriting them. The `docs/install-*.md`
   walkthroughs record real command output, so re-run them against the current CLIs
   rather than editing the output by hand.[^s1]
7. Fleet pairing case 4: the paired dotfiles change deletes the module's
   `modules.tsv` row (no tombstones since 2026-09-16); name it in the PR body.[^s3]

## Check it worked

- `CHECK_BASE=origin/main bin/check.sh` → `ALL CHECKS PASSED`; `bin/fleet-pairing.sh`
  warns `points at a module this checkout no longer has` until the dotfiles row goes.
- `grep -rn '<name>' --exclude-dir=node_modules .` hits only the historical records.
- The PR's `smoke` job is green.

## Verify

- `bin/check.sh` :: `for mod in sorted(p for p in pathlib.Path("modules").iterdir() if p.is_dir()):`
- `bin/check.sh` :: `excluded = f"!modules/{mod.name}/**" in skills`
- `bin/fleet-pairing.sh` :: `points at a module this checkout no longer has`
- `handoff.md` :: `Historical record — do not update.`

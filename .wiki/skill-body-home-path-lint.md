---
type: gotcha
title: "SKILL.md body ~/ path: lint-skills.py fails it, tools/lint.sh passes it"
description: "lint-skills.py: absolute path '~/x' in body fails CI, though tools/lint.sh passes locally; run bin/lint-skills.py after editing a SKILL.md, because the body check is skill-only."
tags: [skills, check-sh]
generated: {by: okf-wiki/claude-haiku-5-5, at: 2026-11-02T16:44:32Z}
verified:
  - {by: okf-wiki/claude-haiku-5-5, at: 2026-11-02T16:44:32Z, commit: 40d5afd2af87}
sources:
  - {id: pr146, resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/146}
  - {id: fix-ba6bbd0, resource: "commit ba6bbd0 in agent-harness-marketplace: writes 'the per-user .qdkrc' instead of ~/.qdkrc"}
---

# SKILL.md body ~/ path: lint-skills.py fails it, tools/lint.sh passes it

## Symptom

PR 146 passed `modules/best-practices/tools/lint.sh` locally, then its first CI run failed with `FAIL modules/best-practices/skills/qpkg-best-practices/SKILL.md: absolute path '~/.qdkrc' in body; reference assets skill-relative`.[^pr146]

## What fails

A home-relative `~/` path anywhere in a `SKILL.md` body fails `bin/lint-skills.py`, even inside a backtick code span. The regex is `ABS_PATH` at `bin/lint-skills.py:51`; the check runs only when the skill is not `claude`-scoped.

## What works

The same `~/.qdkrc` text in `skills/qpkg-best-practices/references/build.md` was not flagged, because the check covers `SKILL.md` bodies only. The fix was to write "the per-user `.qdkrc`".[^fix-ba6bbd0]

## Why

`tools/lint.sh` runs eight checks (rule IDs, links, frontmatter, Requires syntax) and none looks for home or absolute paths. `bin/check.sh` runs `lint-skills.py`, so the gap is only visible in the wider gate.

## Verify

- `bin/lint-skills.py` :: `absolute path`

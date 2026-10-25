---
type: gotcha
title: Research preview verdicts need a live check
description: Research-report preview or stable verdicts can be wrong even when they claim a live test; run the command and quote its warning or its absence before acting on one.
tags: [skills, testing]
generated: {by: okf-wiki/haiku, at: 2026-10-25T19:54:16Z}
verified:
  - {by: okf-wiki/haiku, at: 2026-10-25T19:54:16Z, commit: 2596aa106bc7}
sources:
  - {id: s1, resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/120, title: 2026-10-25 best-practices research report (UVP-063 says uv add-bounds is still preview)}
  - {id: s2, resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/120#issuecomment-6402393225, title: "Correction posted on the report: add-bounds is stable on uv 0.13.5"}
  - {id: s3, resource: modules/best-practices/skills/meta-best-practices/SKILL.md, title: Version floors (Requires.) rule that the verdict fed}
---

# Research preview verdicts need a live check

## Symptom

The weekly research report called `uv add --bounds` "still preview in 0.13.5",
and a rule was about to be tagged "(preview…)" on that basis.[^s1] Running the
command showed no preview warning at all.[^s2]

## What fails

Trusting a preview or stable verdict because the report claims a live test. The
claim can be wrong, and a rule version floor built on it is then wrong too.[^s3]

## What works

Run the feature on the pinned tool version and quote the result:

- `uv add --bounds major idna` and `[tool.uv] add-bounds = "major"` both wrote
  `idna>=3.20,<4.0` with no warning on uv 0.13.5. That is stable.
- A real preview feature warns and names its flag: `uv audit` prints "experimental"
  and says to pass `--preview-features audit-command`; `uv export --format
  cyclonedx1.5` says to pass `--preview-features sbom-export`.

Quote the warning, or its absence, in the change or the reply.

## Why

uv's changelog for 0.10.x lists add-bounds as stable from 0.10.0, which
contradicts the report. Preview status is a flag-level fact, so a command run
settles it faster than reading prose about it.

## Verify

- `modules/best-practices/skills/meta-best-practices/SKILL.md` :: `Version floors`

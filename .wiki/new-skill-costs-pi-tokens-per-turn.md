---
type: gotcha
title: New skill descriptions cost pi tokens per request
description: Skill metadata is injected into every pi request; longer descriptions add recurring per-turn token cost that shipped unmeasured and must be audited in pin-bump PRs.
tags: [pi, modules, performance, injection]
generated: {by: okf-wiki/haiku, at: 2026-10-10T03:19:37Z}
verified:
  - {by: okf-wiki/haiku, at: 2026-10-03T20:40:11Z, commit: ab1e739db62c}
  - {by: okf-wiki/haiku, at: 2026-10-10T03:19:37Z, commit: 246b99c1bbb2}
sources:
  - {id: 337, resource: https://github.com/davidallada/.davidallada-developer-setup/pull/337, title: "Dotfiles v0.2.60 pin bump: transcript-analyze cost audit"}
  - {resource: modules/agent-transcripts/skills/transcript-analyze/SKILL.md, title: "transcript-analyze skill (910-char block, 228 tok/turn, 621-char description; 350 chars after 6ee1320)"}
  - {resource: https://github.com/allada-homelab/agent-harness-marketplace/commit/6ee1320, title: "agent-transcripts 0.8.1: shorten transcript-analyze's description (2026-10-03)"}
---

# New skill descriptions cost pi tokens per request

## Symptom

A new skill is added to a module, or an existing skill's description is lengthened. The paired dotfiles pin-bump PR is flagged in review as high-risk because the per-turn injection cost is unknown or unmeasured.

## What fails

Assuming the repo's 1024-character description lint catches token costs, or not measuring the skill block before shipping. The lint constrains character length, but pi's formatSkillsForPrompt builds an XML <skill> block (name + escaped description + absolute location) that is injected on every request; a 621-character description can balloon to ~910 characters in the block, translating to ~228 tokens per pi turn — a recurring cost shipped unmeasured.

## What works

Before shipping a module with new skills or longer descriptions, measure the injection cost by building the `<skill><name/><description/><location/></skill>` XML block as pi's formatSkillsForPrompt constructs it, then counting its tokens. Keep descriptions short (order 100–200 characters), or exclude the skill from pi injection using a `!modules/<m>/skills/<s>/**` pattern in the dotfiles fleet config if the cost is justified. The paired dotfiles pin-bump PR review names and acknowledges the per-turn cost.

## Why

The marketplace publishes modules; pi (and other harnesses) install from tagged releases. When the dotfiles pin bump PR merges, it decouples from the marketplace — pi starts injecting every visible skill's metadata into every request. Skill metadata (name, XML-escaped description, absolute module path) is formatted as a `<skill>` XML block by pi's `formatSkillsForPrompt` and prepended to every prompt [^337]. The injection audit is declared law in the dotfiles pi/README.md; pin-bump PRs are reviewed against cost and impact. The transcript-analyze skill was flagged as P1 on the v0.2.60 bump after shipping unmeasured: it contributed 910 characters (approximately 228 tokens per turn) from a 621-character description. It was shortened to 350 characters in 6ee1320 (2026-10-03), so the 910/228 figures are historical. The later audit PRs #98–#101 (merged 2026-10-09) trimmed other long descriptions and hid knowledge skills from pi, which is the same cost discipline applied repo-wide. The measurement must happen *before* the PR ships, not after.

## Verify

- `modules/agent-transcripts/skills/transcript-analyze/SKILL.md` :: `description`

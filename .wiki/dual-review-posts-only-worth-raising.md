---
type: decision
title: Dual-review posts only worth-raising findings
description: dual-agent-pr-review posts only blocking, non-blocking and unresolved findings, always as a pending draft; nits, NOT_WORTH_RAISING, author-deferred and thread-covered findings stay in final.md, because low tiers were noise.
tags: [skills, github]
generated: {by: okf-wiki/opus, at: 2026-10-21T12:27:19Z}
verified:
  - {by: okf-wiki/haiku, at: 2026-10-21T12:26:59Z, commit: cf48a38493be}
  - {by: okf-wiki/opus, at: 2026-10-21T12:27:19Z, commit: cf48a38493be}
sources:
  - {id: pr115, resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/115}
  - {id: audit, resource: "Outcome audit 2026-10-21: 63 comments delivered on 12 PRs (teamlumos lumos/ai-agents/infra), outcomes checked against later commits and replies"}
---

# Dual-review posts only worth-raising findings

## Decision

`dual-agent-pr-review` (0.1.16) posts no nits inline. Reconciliation may rule a non-blocking finding NOT_WORTH_RAISING; it, author-deferred findings on a re-review, and findings an existing live thread already covers are not posted. Every review stays a pending draft; nothing is submitted by the workflow. Recommend Request changes when the draft has a Blocking or Open-question comment, otherwise Comment [^pr115].

## Why

The audit found Blocking comments were reliable: 10 of 10 were significant [^audit]. The low tiers were noise: Nit had 0 significant and 8 noise of 16, and authors fixed nits anyway, costing a round. Non-blocking had 5 significant, 20 minor and 5 noise of 30 [^audit]. About 10 comments duplicated an existing bot or human thread, and re-reviews re-posted items the author had already ticketed [^audit]. The user hand-trimmed drafts to blockers, keeping 3 of 11 [^audit].

## Rejected alternatives

- Dropping the upward "broken is blocking" calibration: it is what keeps Blocking at 10 of 10. One real bug was still labelled a nit on lumos#42138 [^audit].
- Posting nits in the review body: the body is a short index and must not carry findings.
- Keeping a direct submit path: the user asked for drafts always.

## Revisit when

A new audit shows nits or NOT_WORTH_RAISING findings catching real defects, or Blocking precision falls below its current level.

## Verify

- `modules/dual-agent-pr-review/skills/dual-agent-pr-review/WORKFLOW.md` :: `Always a draft`
- `modules/dual-agent-pr-review/skills/dual-agent-pr-review/schemas/verdicts.json` :: `NOT_WORTH_RAISING`

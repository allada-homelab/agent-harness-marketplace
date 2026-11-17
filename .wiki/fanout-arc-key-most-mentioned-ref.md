---
type: decision
title: Fan-out arcs key each session on its most-mentioned PR or ticket
description: corpus.py arc() dedupes sessions by their most-mentioned PR or ticket; linking every shared reference merged 28 of 75 sessions into one arc.
tags: []
generated: {by: okf-wiki/unknown, at: 2026-11-17T02:00:10Z}
verified:
  - {by: okf-wiki/unknown, at: 2026-11-17T02:00:10Z, commit: 9af86e4c0897}
sources:
  - {id: measure-2026-11-16, resource: "Measurement of one week of interactive sessions (75 sessions), 2026-11-16"}
  - {id: arc-fn, resource: "modules/agent-transcripts/skills/transcript-analyze/corpus.py :: arc"}
---

# Fan-out arcs key each session on its most-mentioned PR or ticket

## Decision

`arc()` returns the single PR URL or ticket id a human named most in a session; the first-named wins a tie. [^arc-fn] `pick()` keeps one session per arc, heaviest typist first. Scripted runs use the same key (`run:<project>:<arc>`), so rounds of different PR reviews in one project split into separate runs.

## Why

Measured on one week (75 interactive sessions) [^measure-2026-11-16]: linking sessions transitively through any shared PR or ticket merged 28 of them into one arc, because one long project touches the same stack of PRs. That leaves a single sample standing for a whole project. Keying on the most-mentioned reference kept 16 distinct top-typing sessions and dropped only true siblings.

## Rejected alternatives

- Transitive linking through any shared reference: over-merges long projects into one arc (28 of 75).
- A stoplist for the ticket regex: it has rare false hits (2 of 561 sessions over a month, e.g. GPT- and GUIDE- prefixes), judged too rare to justify a stoplist.

## Revisit when

The ticket regex false hits grow, or a sample shows the most-mentioned reference splitting sessions that belong together.

## Verify

- `modules/agent-transcripts/skills/transcript-analyze/corpus.py` :: `def arc(texts: list[str]) -> str | None:`

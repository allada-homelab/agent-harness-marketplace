---
name: reflect
description: Measure whether this repo's .wiki/ and its prompting actually help — consult rate, hits versus gaps, rediscovery of things the wiki already said, capture precision and misses — from the agent-transcripts index and git, then fix the wiki's content and draft evidence-backed proposals for the okf-wiki module's prompts. Use when the digest says "reflect due" or the user asks whether the wiki is working or how to improve it.
user-invocable: true
argument-hint: "[--days N] [--fanout N]"
---

# reflect

Arguments, if any: $ARGUMENTS (on some harnesses they arrive as text after this skill
instead). Let `<okf>` be the absolute path of `../wiki/okf.py`.

## 1. Count

`python3 <okf> stats [--days N]` prints JSON (everything above its last line). If
`transcripts.available` is false, say why and stop: the agent-transcripts module has to be
installed and ingested first. If `digest_visible` is false, report that injected digests are
not reaching the transcript index, which makes the consult rate unmeasurable.

## 2. Judge

Sample up to 12 sessions in this repo from the window: those that cited concepts, those with
`GAP:` lines, and plain sessions with no wiki use at all. Get bounded excerpts with the
agent-transcripts `transcript-query` skill. Dispatch one `okf-wiki:auditor` per excerpt,
at most `python3 <okf> fanout` in flight. Each returns a verdict on: consulted, helped,
rediscovery (the agent re-derived something a listed concept already said), wrong (a
concept contradicted by what happened), missed capture.

## 3. Score and diagnose

Report one table:

| Question | Signal | Value | Points at |
|---|---|---|---|
| Consulted? | consulted_sessions / digest_sessions | | injected rule, skill descriptions |
| Hit? | cited vs gaps | | content gaps, capture bar |
| Helped? | auditor "helped" rate | | description quality |
| Rediscovery | auditor count | | digest, descriptions, consult prompting |
| Right? | auditor "wrong" + heal outcomes | | anchors, capture accuracy |
| Capture precision | git.deleted, never_cited, deprecated | | capture bar |
| Capture recall | auditor "missed capture" | | nudge, capture rule |

## 4. Act

- **Wiki content** (apply now, with receipts): rewrite descriptions of concepts that were
  rediscovered instead of used, deprecate concepts never cited in the window that fail the
  capture bar, merge duplicates, capture what the auditors found missing.
- **Module prompts** (never edit them here): the injected rule, digest format, skill and
  agent text and capture bar live in the okf-wiki module. Write a proposal: the metric, the
  evidence (session ids and excerpts), the exact text change, and the expected effect. Offer
  to open it as a pull request against the marketplace repository; the user decides.

## 5. Mark

`python3 <okf> stats --mark` resets the "reflect due" counter. Run it only after reporting.

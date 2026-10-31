---
name: reflect
description: Measure whether .wiki/ helps (consults, hits vs gaps, rediscovery, missed captures) from transcripts and git, then fix it and propose prompt changes. Use when the digest says "reflect due" or asked if the wiki works.
user-invocable: true
argument-hint: "[--days N] [--fanout N]"
---

# reflect

Arguments, if any: $ARGUMENTS (on some harnesses they arrive as text after this skill
instead). Let `<okf>` be the absolute path of `../wiki/okf.py`.

## 1. Count

`python3 <okf> stats [--days N]` prints JSON (everything above its last line). If
`transcripts.available` is false, say why and stop: the agent-transcripts module has to be
installed and ingested first. If `transcripts.capabilities.digest_visible` is false, say so:
injected digests are not reaching the transcript index, which makes the consult rate
unmeasurable.

## 2. Judge

Sample up to 12 sessions in this repo from the window: those that cited concepts, those with
`GAP:` lines, and plain sessions with no wiki use at all. Get bounded excerpts with the
agent-transcripts `transcript-query` skill. Excerpts hold message text only, so for each
session also query its Read-type `tool_calls` whose arguments name `.wiki/<id>.md`. Take the
concept ids and descriptions as of the window start from `git show <commit>:.wiki/index.md`,
where `<commit>` is `git rev-list -1 --before=<window start> HEAD`. Dispatch one
`okf-wiki:auditor` per excerpt with all three (excerpt, Read list, concept list), at most
`python3 <okf> fanout` in flight. Each returns a verdict on: consulted, helped,
rediscovery (the agent re-derived something a listed concept already said), wrong (a
concept contradicted by what happened), missed capture.

## 3. Score and diagnose

Report one table:

| Question | Signal | Value | Points at |
|---|---|---|---|
| Consulted? | consulted_sessions (a concept cited, or any Read under `.wiki/` including `index.md`) / digest_sessions | | injected rule, skill descriptions |
| Hit? | concepts Read (`transcripts.read`) vs gaps | | content gaps, capture bar |
| Helped? | auditor "helped" rate | | description quality |
| Rediscovery | auditor count | | digest, descriptions, consult prompting |
| Right? | auditor "wrong" + heal outcomes | | anchors, capture accuracy |
| Capture precision | git.deleted, never_cited, deprecated | | capture bar |
| Capture recall | auditor "missed capture" | | nudge, capture rule |

## 4. Act

- **Wiki content** (apply now, with receipts): rewrite descriptions of concepts that were
  rediscovered instead of used, deprecate concepts never cited in the window that fail the
  capture bar, merge duplicates, capture what the auditors found missing. NEVER deprecate on
  `never_cited` unless `transcripts.capabilities.reads` is true: without Read data an unused
  concept and an unmeasured one look the same.
- **Module prompts** (never edit them here): the injected rule, digest format, skill and
  agent text and capture bar live in the okf-wiki module. Write a proposal: the metric, the
  evidence, the exact text change, and the expected effect. Offer to open it as a pull
  request against the marketplace repository; the user decides. That repository is public:
  the proposal carries metric names, counts and synthetic repros only — never session ids,
  transcript excerpts, concept text or details that identify this repo. The evidence stays in
  the local transcript cache or scratch.

## 5. Mark

`python3 <okf> stats --mark` resets the "reflect due" counter. Run it only after reporting.

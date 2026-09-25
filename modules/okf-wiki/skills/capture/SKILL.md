---
name: capture
description: Save a durable, non-obvious finding to this repo's .wiki/ — or re-verify a stale concept — by briefing the cheap okf-wiki scribe agent in the background and printing a one-line receipt. Use unprompted before finishing any task that taught something grepping the code would not reveal, when the session-start digest marks a concept ⚠ stale, or when the user says "capture this", "remember this in the wiki" or "add to the wiki".
user-invocable: true
argument-hint: "[finding to capture, or: re-verify <id>]"
---

# capture

Arguments, if any: $ARGUMENTS (on some harnesses they arrive as text after this skill
instead). Read `../wiki/SKILL.md` first if you have not this session.

## 1. Decide (you, not the scribe)

You hold the context; the scribe does not. For each candidate finding apply the capture bar
from the wiki contract. Drop anything a grep would find. Several findings are several
concepts; one finding is one concept even if it touched many files.

Check whether an existing concept already covers it: the session digest lists them, and
`python3 <okf> new <type> <slug>` exits 3 with the near-duplicates. Updating beats creating.

## 2. Brief

One brief per concept, three to six lines:

```
okf: <absolute path of ../wiki/okf.py>
mode: create | update <id> | re-verify <id>
type: gotcha
claim: <one sentence, the description to write>
why: <the reason, the evidence you saw: commits, files, error text>
anchor: <path> :: <symbol>   (or: none: <reason>)
```

## 3. Dispatch

Send each brief to `okf-wiki:scribe` in the background (see "Dispatching" in the wiki
contract). For several briefs run `python3 <okf> fanout` and keep at most that many scribes
in flight; give each a different concept so no two write the same file. Pass `--fanout N`
from the arguments through to `fanout` if the user gave one.

## 4. Receipt

When a scribe returns, print its receipt line (`wiki: +gotcha/<id>`, `wiki: ~healed/<id>`,
`wiki: ✗ <id> — <reason>`). Never drop a failure silently. If you could not dispatch, do the
scribe's steps yourself and mark the receipt ` (inline)`.

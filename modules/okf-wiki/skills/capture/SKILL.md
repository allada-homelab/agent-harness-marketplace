---
name: capture
description: Save a durable, non-obvious finding to this repo's .wiki/ — or re-verify a stale concept — by briefing the cheap okf-wiki scribe agent in the background and printing a one-line receipt. Use unprompted before finishing any task that taught something grepping the code would not reveal, when the session-start digest marks a concept ⚠ stale, or when the user says "capture this", "remember this in the wiki" or "add to the wiki".
user-invocable: true
argument-hint: "[finding to capture, or: re-verify <id>]"
---

# capture

Arguments, if any: $ARGUMENTS (on some harnesses they arrive as text after this skill
instead). Read `../wiki/SKILL.md` first if you have not this session.
Let `<okf>` be the absolute path of `../wiki/okf.py`.

## 1. Decide (you, not the scribe)

You hold the context; the scribe does not. For each candidate finding apply the capture bar
from the wiki contract. Drop anything a grep would find. Several findings are several
concepts; one finding is one concept even if it touched many files.

Check whether an existing concept already covers it: the session digest lists them, and
`python3 <okf> new <type> <slug> --check` exits 3 with the near-duplicates and writes
nothing; never probe with plain `new`, which creates the file. Updating beats creating.

## 2. Brief

One brief per concept, three to seven lines:

```
okf: <absolute path of ../wiki/okf.py>
root: <absolute path of the checkout the change lives in — your task's worktree>
mode: create | update <id> | re-verify <id>
type: gotcha
claim: <one sentence, the description to write>
why: <the reason, the evidence you saw: commits, files, error text>
anchor: <path> :: <symbol>   (or: none: <reason>)
```

`root` is not optional when you work in a worktree: without it the scribe writes into the
`.wiki/` of whatever checkout its own working directory is in, which can be the shared main
checkout another session is using.

## 3. Dispatch

Send each brief to `okf-wiki:scribe` in the background (see "Dispatching" in the wiki
contract). For several briefs run `python3 <okf> fanout` and keep at most that many scribes
in flight; give each a different concept so no two write the same file. Pass `--fanout N`
from the arguments through to `fanout` if the user gave one.

**Stall rule.** A scribe that has not answered is working, not wedged: a cold start alone can
take minutes with nothing on disk. Do not interrupt, re-dispatch or hand-write its concept
before about 30 minutes of wall-clock time since dispatch, and not even then without evidence
of no progress — no receipt, and its `.wiki/<id>.md` absent or with an mtime unchanged for
that whole stretch. Past that bar, stop that one scribe first, then redo its concept (a new
scribe, or inline with ` (inline)`), so two writers never share a file.

## 4. Receipt

When a scribe returns, print its receipt line (`wiki: +gotcha/<id>`, `wiki: ~healed/<id>`,
`wiki: ✗ <id> — <reason>`). Never drop a failure silently. If you could not dispatch, do the
scribe's steps yourself and mark the receipt ` (inline)`.

## 5. Commit it with the work

Scribes write after you dispatch them, so a commit made before their receipts misses the
concept, and a `.wiki/` file mid-write is not yet valid. Never commit, revert or delete a
`.wiki/*` file while its scribe's receipt is outstanding — `python3 <okf> --root <root>
validate <id>` must pass first. Once every receipt is in, commit `.wiki/` in `<root>`, in the
commit that carries the change that taught it or on this branch right after, so the knowledge
ships in the same PR. A capture with no work branch to ride on (the work already merged)
goes up as its own PR; when the user's instructions standing-approve wiki-only PRs, finish it
with `pr-flow watch --merge-if-only .wiki/` (on pi and dsh, where `pr-flow` is not on
`PATH`, run the pr-flow skill's `pr-flow.py` with `python3`) instead of waiting for a per-PR yes — and stage the
`.wiki/index.md` that `validate` regenerates, or the index drifts from the concept.
Never `rm` or otherwise delete a concept file in a shared checkout (the
main checkout while you work in a worktree): another session's scribe may be writing it. To
drop a concept of your own, remove it on your branch after its receipt.

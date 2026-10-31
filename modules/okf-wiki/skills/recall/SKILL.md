---
name: recall
description: Answer a question from this repo's .wiki/ with cited, freshness-checked concepts. Use before non-trivial work when the session-start digest is not enough — "what do we know about X", "has this broken before", "why is Y done this way" — and before re-deriving something the wiki may already hold.
user-invocable: true
argument-hint: "<question>"
---

# recall

Question: $ARGUMENTS (on some harnesses it arrives as text after this skill instead).
Let `<okf>` be the absolute path of `../wiki/okf.py`.

1. Grep `.wiki/index.md` for the question's key terms and their synonyms; the digest lists
   only some concepts. Read the top hits, at most about eight `.wiki/<id>.md` files.
2. `python3 <okf> fresh <ids...>` for the concepts you will rely on.
3. Answer with one short claim per point, each ending `concept:<id>`. Flag a STALE (⚠)
   concept's claim as a lead to check, not a fact; if your task relies on it, run the capture
   skill in re-verify mode for that id in the background and keep working. Flag a TOUCHED
   concept too: its anchors still pass, but its anchor file changed since it was verified.
4. When nothing covers part of the question, add a line `GAP: <question>`. Do not fill it from
   general knowledge; a GAP is a candidate for capture once you have learned the answer.

Never paste a whole concept into your reply to the user; cite `concept:<id>` instead.

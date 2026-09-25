---
name: recall
description: Answer a question from this repo's .wiki/ with cited, freshness-checked concepts, using the cheap okf-wiki reader agent in an isolated context. Use before non-trivial work when the session-start digest is not enough — "what do we know about X", "has this broken before", "why is Y done this way" — and before re-deriving something the wiki may already hold.
user-invocable: true
argument-hint: "<question>"
---

# recall

Question: $ARGUMENTS (on some harnesses it arrives as text after this skill instead).

1. Dispatch `okf-wiki:reader` with a brief of three lines: the question, what you are about to
   do with the answer, and `okf: <absolute path of ../wiki/okf.py>` (see "Dispatching" in
   `../wiki/SKILL.md`). One reader is enough; do not fan out.
2. The reader returns at most about 1500 characters: claims each cited `concept:<id>`, plus
   `STALE: <id> (<why>)` and `GAP: <what is missing>` lines.
3. Use the cited claims. For each `STALE:` line, run the capture skill in re-verify mode for
   that id, in the background, and keep working. Treat a stale claim as a lead to check, not
   a fact.
4. A `GAP:` is a candidate for capture once you have learned the answer yourself.

Never paste a whole concept into your reply to the user; cite `concept:<id>` instead.

---
name: ste-writing
description: Write prose about 80% of the way to ASD-STE100 (Simplified Technical English), the controlled language from aerospace maintenance documentation. Use this every time the user names the style in any phrasing — "STE", "ste", "STE100", "ASD-STE100", "Simplified Technical English", "controlled language", "the Karpathy 80% writing thing" — whether they want new text written in it, existing text or a file rewritten in it, or the rest of the session answered in it. Do not use when the user only asks for clearer, shorter, simpler or plain-English text without naming the style, and never for code comments or commit subjects, which keep their own conventions.
user-invocable: true
argument-hint: "[what to write, or the text or file to rewrite]"
tags: [writing]
---

# STE writing

Target: $ARGUMENTS. When no target is given, apply the style to the prose of
your reply to the current request. When the user asked for the style for the
whole session, apply it to every later reply too.

Write your prose about 80% of the way to ASD-STE100 (Simplified Technical
English): follow the spirit of the specification's writing rules, but it is
fine to use technical terms that the specification's dictionary does not
approve. The reader is a tired engineer on a phone between meetings. They must
get every fact in one pass and never re-read a sentence.

Three corrections, because models over-apply the specification:

- The 20-word (instruction) and 25-word (description) limits are ceilings, not
  targets. Aim for an average of 12 to 16 words and vary the length. A run of
  6-word sentences that all start with the same subject reads as robotic. Use
  pronouns and connecting words (because, so, which, when) where they make one
  clear sentence out of two fragments.
- The medium wins over the style. A Slack message stays a message: no headers,
  no bold labels, the register of a colleague. A commit body, a PR template, a
  README section, or a docstring keeps its own convention. Apply the rules only
  to the prose inside the form the task asks for.
- Code, commands, paths, identifiers, error text, and quoted output are
  reproduced verbatim. State unconfirmed things as unconfirmed; a shorter
  sentence must not make a claim stronger than the source.

That is the whole instruction; adding the specification's rule list to it
measured worse on every model tier tested. The rules, which ones the 80% keeps
and drops and why, where the style fits, and the measurements are in
`./references/ste-rules.md`. Read it when the user asks what the style is or
wants a stricter or looser setting.

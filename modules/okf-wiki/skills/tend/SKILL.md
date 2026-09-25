---
name: tend
description: Health report for this repo's .wiki/ — validation errors and warnings, stale, unanchored and unverified concepts, orphans nothing links to, and likely duplicates — with an offer to heal the stale ones in one batch. Use when the user asks to "tend", "check", "clean up" or "audit" the wiki, or when the digest shows invalid or stale concepts.
user-invocable: true
argument-hint: "[--fanout N]"
---

# tend

Arguments, if any: $ARGUMENTS (on some harnesses they arrive as text after this skill
instead). Read-only until the user agrees to a fix. Let `<okf>` be the absolute path of
`../wiki/okf.py`.

1. `python3 <okf> validate` and `python3 <okf> fresh`.
2. Orphans: concepts no other concept links to. Grep `.wiki/` for `](./<id>.md` for each id.
3. Likely duplicates: concepts whose titles and tags overlap heavily. Judge from `index.md`.
4. Report in this order, one line each, grouped under headings: ERRORs (must fix), STALE,
   UNVERIFIED and UNANCHORED, duplicates, orphans, then a count of WARNs.
5. Offer, as one question: heal every STALE and UNVERIFIED concept (scribes in re-verify
   mode, at most `python3 <okf> fanout` in flight), merge the duplicates, fix the errors. Do
   only what the user accepts, and print a receipt per concept.

Never delete a concept: deprecate it (`status: deprecated` plus the reason), so git keeps it
reviewable.

---
name: tend
description: Health report for .wiki/ (errors, stale and unverified concepts, orphans, duplicates, tags to merge), offering to heal in one batch. Use to "tend", "check", "clean up" or "audit" the whole wiki, or on invalid concepts.
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
4. Tags: `python3 <okf> tags --suggest` for spelling and plural variants, redundant and
   malformed tags. Then read `python3 <okf> tags` yourself for what a script cannot tell —
   synonyms and acronyms (`monitoring` and `observability`; `ha` is high-availability in one
   wiki, home-assistant in another — check with `tags <tag>` before merging) — and turn both
   into one proposed map: `old -> new` or `old -> drop` per line, each malformed tag mapped to
   its kebab form.
5. Report in this order, one line each, grouped under headings: ERRORs (must fix), STALE,
   UNVERIFIED and UNANCHORED, duplicates, orphans, tags, then a count of WARNs and of TOUCHED
   concepts (an anchor file changed but the anchors still pass; not ⚠, nothing to heal).
6. Offer, as one question: heal every STALE and UNVERIFIED concept (scribes in re-verify
   mode, briefed and committed as `../capture/SKILL.md` §2–5 say, `root:` line included; at most `python3 <okf> fanout` in flight), merge the duplicates, apply the tag map,
   fix the errors. Do only what the user accepts, and print a receipt per concept. Apply the
   tag map yourself, one `python3 <okf> retag` per line, and commit it on its own: `fresh`
   reads a commit that touches a concept as that concept being rewritten alongside its code,
   so retags folded into a code commit hide any drift that commit causes.

Never delete a concept: deprecate it (`status: deprecated` plus the reason), so git keeps it
reviewable.

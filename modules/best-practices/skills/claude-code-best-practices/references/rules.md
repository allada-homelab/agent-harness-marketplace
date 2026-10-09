# CC rule-file rules

Detailed entries for `CC-025..CC-028` — files under `.claude/rules/`.
Each follows the four-part **What / Why / How / When NOT to apply** shape.

---

## CC-025 — Scope rules with `paths:`

**What.** A rule that applies to a subset of files has `paths:`
frontmatter listing globs.

**Why.** An unscoped rule loads at launch in every session, which makes
it mechanically the same as putting it in CLAUDE.md — it pays the
always-loaded cost for guidance most sessions don't need.

**How.**

```markdown
---
paths: ["src/api/**/*.ts"]
---
Handlers validate input with the shared zod schemas in src/api/schemas.
```

**When NOT to apply.** A rule that must hold in every session, or must
survive compaction, is deliberately unscoped (CC-028).

---

## CC-026 — One concern per rule file

**What.** Keep each rule file short and about one concern.

**Why.** A rule file loads as a unit; bundling unrelated concerns loads
all of them whenever one applies, and makes the `paths:` scope too broad
for most of its content.

**How.** Split `backend.md` into `migrations.md` (scoped to the
migrations directory) and `api-handlers.md` (scoped to the handlers).

**When NOT to apply.** Closely related guidance with the same scope can
share a file.

---

## CC-027 — Path-scoped rule over nested CLAUDE.md for cross-cutting concerns

**What.** For a concern that appears in several directories ("migrations
are append-only"), use one path-scoped rule with several globs instead of
copies in each directory's CLAUDE.md.

**Why.** Copies drift apart; a single rule has one place to change, and
its globs say exactly where it applies.

**How.**

```markdown
---
paths: ["services/*/migrations/**"]
---
```

**When NOT to apply.** Guidance specific to one directory belongs in that
directory's CLAUDE.md.

---

## CC-028 — Only unscoped rules survive compaction

**What.** A constraint that must hold for the whole session lives in an
unscoped rule or the project-root CLAUDE.md. Rules with `paths:` reload
only when a matching file is touched again after compaction.

**Why.** Claude Code re-injects the project-root CLAUDE.md and unscoped
rules from disk after compaction, but path-scoped rules load into message
history when their trigger file is touched and are summarized away with
it. A path-scoped rule that must always apply can be silently missing for
the rest of a long session.

**How.** If a scoped rule must persist across compaction, drop its
`paths:` frontmatter or move it to the project-root CLAUDE.md — and weigh
that against its every-session cost (CC-025).

**When NOT to apply.** Guidance that only matters while working on the
matching files can stay scoped; it comes back when those files are
touched.

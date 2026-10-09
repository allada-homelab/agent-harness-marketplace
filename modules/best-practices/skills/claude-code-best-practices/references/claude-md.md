# CC CLAUDE.md rules

Detailed entries for `CC-019..CC-024` — memory files (`CLAUDE.md`,
`CLAUDE.local.md`, nested and user-level CLAUDE.md). Each follows the
four-part **What / Why / How / When NOT to apply** shape.

## Contents

- CC-019 — Each CLAUDE.md under 200 lines
- CC-020 — Include what Claude can't guess; exclude what it can
- CC-021 — CLAUDE.md is an index; imports don't save context
- CC-022 — Know how nested CLAUDE.md files load
- CC-023 — Say what to preserve through compaction
- CC-024 — Own and audit checked-in CLAUDE.md

---

## CC-019 — Each CLAUDE.md under 200 lines

**What.** Keep each CLAUDE.md under 200 lines, and keep the files that
load together in every session small in total.

**Why.** Always-loaded files are paid for on every turn and dilute each
other. Two symptoms point here: Claude ignores a rule that exists (the
file is usually too long), or asks a question the file already answers
(the phrasing is ambiguous).

**How.** Measure with `wc -l CLAUDE.md`; move procedures to skills
(CC-014), scoped guidance to rules (CC-015) and reference material out
(CC-017) until it fits.

**When NOT to apply.** Never as a ceiling to exceed; a much shorter file
is better when it covers what's needed.

---

## CC-020 — Include what Claude can't guess; exclude what it can

**What.** Include commands Claude can't guess, style rules that differ
from defaults, the test runner and how to run a single test, repository
etiquette (branches, PR conventions), architectural decisions,
environment quirks (required environment variables) and non-obvious
gotchas. Exclude anything Claude can learn by reading the code, standard
conventions, detailed API docs (link instead), frequently changing
information, tutorials and file-by-file descriptions of the codebase.

**Why.** The included items are exactly what Claude gets wrong without
being told; the excluded ones it can derive, and they cost context on
every turn while going stale.

**How.**

```markdown
## Commands
- Single test: `uv run pytest tests/test_api.py::test_login -q`
- The API tests need `DATABASE_URL`; `make db` starts one.
```

**When NOT to apply.** Never.

---

## CC-021 — CLAUDE.md is an index; imports don't save context

**What.** CLAUDE.md gives an overview and points to where details live.
For content needed only sometimes, use skills or path-scoped rules, not
`@path` imports.

**Why.** An imported `@path` file loads at launch with the file that
imports it, so splitting CLAUDE.md into imports reorganizes it without
reducing what every session pays for.

**How.**

```markdown
Deployment runbook: the `deploying` skill.   (loads on demand)
@docs/deploy.md                              (loads every session)
```

**When NOT to apply.** An import is right for content every session
needs that lives in another file (a shared team conventions file).

---

## CC-022 — Know how nested CLAUDE.md files load

**What.** A subdirectory CLAUDE.md loads once Claude reads, writes or
edits a file in that directory, and is summarized away at compaction
until that directory is touched again. In a monorepo, give each team's
area its own subdirectory CLAUDE.md; developers can skip areas they never
touch with the `claudeMdExcludes` setting.

**Why.** Content placed in a subdirectory file is not present at session
start and not guaranteed after compaction; an instruction that must hold
for the whole session in that area can silently disappear mid-session.

**How.** Put area-specific conventions in `services/billing/CLAUDE.md`;
put anything that must survive compaction in the project-root file or an
unscoped rule.

**When NOT to apply.** Single-package repos may need only the root file.

---

## CC-023 — Say what to preserve through compaction

**What.** Add a line telling Claude what to keep when the conversation is
summarized.

**Why.** Compaction summarizes the conversation history; without
guidance, the summary can drop the details a long task depends on (which
files changed, how to run the tests).

**How.**

```markdown
When compacting, preserve the list of modified files and the test commands.
```

**When NOT to apply.** Projects whose sessions are short and rarely
compact can skip it.

---

## CC-024 — Own and audit checked-in CLAUDE.md

**What.** A checked-in CLAUDE.md has an owner and is reviewed like code.
Run `/doctor` to get proposed cuts for content Claude can derive from the
codebase, and `/doctor prompt-audit` to find outdated or conflicting
instructions.

**Why.** CLAUDE.md drifts: commands get renamed, conventions change, and
nobody notices the instruction file still says the old thing — which
Claude then follows.

**How.** Add CLAUDE.md to CODEOWNERS; run `/doctor prompt-audit` when
reviewing changes to it.

**When NOT to apply.** A personal, uncommitted `CLAUDE.local.md` needs no
owner beyond its author.

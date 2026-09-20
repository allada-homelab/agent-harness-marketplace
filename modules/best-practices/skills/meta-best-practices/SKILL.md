---
name: meta-best-practices
description: Use when adding, editing, or reviewing rules in the best-practices library — covers the rule-ID format (PREFIX-NNN), severity scale, four-part What/Why/How/When-NOT-to-apply reference structure, SKILL.md shape, third-person description-field rules, and how to use tools/new-skill.sh + tools/new-rule.sh + tools/lint.sh + tools/render-index.sh. Activate on phrases like "best practices format", "add a rule", "rule format", "severity scale", "new domain skill", or when generating content for any *-best-practices skill.
---

# Library format spec

The best-practices library is a collection of domain skills
(`containers-best-practices`, `uv-best-practices`,
`python-best-practices`, ...). All skills follow one format. This
skill is the format spec — when the agent is about to add a rule, write a
new skill, or refactor the library, read these rules first to keep
output consistent.

The human-readable companion is
[`CONVENTIONS.md`](../../CONVENTIONS.md) at the module root. The two
files cover the same ground; this one is shaped for in-session use.

## When to apply this skill

Activate when any of these are true:

- About to add a new rule to an existing `*-best-practices` skill.
- About to create a new domain skill in the library.
- Editing a `SKILL.md` description field (most load-bearing thing).
- Reviewing a PR that touches `modules/best-practices/`.
- The user asks about rule format, severity scale, or library conventions.

## Library shape

```
modules/best-practices/
├── CONVENTIONS.md                  # human spec (mirrors this skill)
├── INDEX.md                        # generated cross-skill rule index
├── skills/<domain>-best-practices/
│   ├── SKILL.md                    # entry point: description + scope + rule index
│   └── references/                 # detail, keyed by rule ID
│       ├── <topic>.md
│       └── ...
├── tools/                          # authoring scripts (see "Adding content")
└── tests/activation-examples.md    # "this query should activate this skill"
```

One skill per domain. One reference file per topic within a domain.
Topic names are lowercased prefixes (`dockerfile.md` for `DOCKER-*`,
`security-build.md` when one file holds multiple prefixes).

## Rule IDs

Format: **`<PREFIX>-<NNN>`** where prefix is 2–7 uppercase letters and
NNN is zero-padded to at least 3 digits.

| Skill | Prefixes in use |
|---|---|
| `containers-best-practices` | `DOCKER`, `DEVC`, `COMPOSE`, `BUILDX`, `SEC`, `UV` |
| `uv-best-practices` | `UVP` |
| `python-best-practices` | `PY` |
| `frontend-best-practices` | `FE` |

Rules:

- One prefix can span multiple reference files only if the
  alternative (separate prefixes) creates more confusion than it
  resolves. Within `containers-best-practices`, `SEC-*` deliberately
  spans `security-build.md` (the main file) but cross-references
  rules elsewhere.
- New skills introduce new prefixes. **Never re-use a prefix
  that's already in another skill in the library** — the
  `tools/lint.sh` cross-skill collision warning catches this.
- Number assignment is first-come-first-served. Gaps are allowed
  (for deprecated rules). **Never reuse a published number** with a
  different rule, even after deletion.

## Severity (assigned by audits, not stored in the rule)

The scale: **high / medium / low / needs-judgment**. Where each
sits:

- **high** — active security risk, data-loss risk, or silently
  broken behavior that ships to production. Example: `SEC-013` —
  `.git/` in image leaks history.
- **medium** — bloat, cache misbehavior, observable performance
  regression, or likely-but-not-certain failure. Example:
  `DOCKER-019` — `apt-get update` and `install` in separate `RUN`s.
- **low** — quality-of-life, readability, hygiene. The project
  works without fixing it. Example: `DOCKER-023` — missing OCI
  labels.
- **needs-judgment** — rule may or may not apply depending on
  context the file alone can't determine. Surface as a question,
  not a finding.

**Severity is NOT in the rule body.** It's owned by the audit command
for the domain (e.g. the `containers-audit` skill decides severity for
`DOCKER-*` rules). The same rule can be high-severity in production
and low-severity in a throwaway dev container — context decides.

## Reference-file rule entry shape

Every rule in `references/*.md` is exactly this four-part structure:

```markdown
## RULE-NNN — One-line title

**What.** Restate the rule precisely, in one paragraph at most.

**Why.** A concrete failure mode if you violate it — real footgun, not
theory. Cite a CVE, documented incident, upstream bug, or named
consequence.

**How.** A minimal correct snippet. Real code that compiles and
runs, not pseudocode. If multiple correct approaches exist, show the
simplest one; mention alternatives in prose.

**When NOT to apply.** Exceptions and trade-offs. Always include
this section. If a rule has no real exceptions, write "Never.
<reason>." explicitly rather than omitting the section.
```

Strict requirements:

- **Heading is exactly `## RULE-NNN — title`** (two hashes, rule ID,
  em dash, title). This is what `lint.sh` matches.
- **What/Why/How/When NOT to apply are bold-prefixed paragraphs**,
  not subheadings.
- **Don't omit "When NOT to apply".** Even "Never" rules state it
  explicitly.
- **No TODO/WIP markers in committed rules.** Stubs at the
  whole-file level are fine while scaffolding a new skill; half-
  written rule entries are not.

## SKILL.md shape

```markdown
---
name: <domain>-best-practices
description: <see "description field rules" below>
---

# <Domain> best practices

A curated rule set for <one-sentence scope>. Each rule has a stable
ID and a one-line summary. Full **What / Why / How / When-not-to-apply**
entries live in `references/`.

## When to apply this skill

Activate when any of these are true:

- <specific trigger 1>
- <specific trigger 2>

## How to use the rule index

1. Scan the relevant section(s) below for rule IDs that apply.
2. For each rule, open the corresponding `references/` file and read
   **only that rule's entry** — they're keyed by ID.
3. Cite the rule ID when explaining a change.

## Rules — <Topic 1>

See [`references/<topic1>.md`](references/<topic1>.md).

- **PREFIX-001** — One-line summary.
- **PREFIX-002** — One-line summary.
```

The SKILL.md body is **lean**. Detail lives in `references/`. The
SKILL.md you read is the entry point — the agent loads `references/<topic>.md`
on-demand when applying a specific rule.

## Description-field rules

The `description:` field is what the harness matches against the user's
current context to decide whether to activate the skill. Bad
description = skill never fires; broad description = fires on
unrelated prompts.

1. **Third person, imperative.** "Use when …" / "Activate on …" —
   never "I" or "you" or "This skill".
2. **Lead with concrete triggers.** File types, tool names, command
   names — things that literally appear in prompts or files in
   context.
3. **Mention rule prefixes** so prompts referencing a specific ID
   route here.
4. **Be specific about scope.** "uv as a Python project tool" beats
   "Python best practices" if both might match.
5. **No marketing language.** "comprehensive", "ultimate",
   "essential" are noise. Trigger keywords are signal.

Good:

> Use when working with Dockerfiles, docker-compose, buildx, or dev
> containers. Covers DOCKER-, COMPOSE-, DEVC-, BUILDX-, SEC-, UV-
> rule families.

Bad:

> Comprehensive best practices for modern containerization
> workflows.

## Adding content

Always use the tools. They enforce the format mechanically.

### New domain skill

```bash
cd modules/best-practices
tools/new-skill.sh python    # creates skills/python-best-practices/
```

Then edit `skills/python-best-practices/SKILL.md`:

- Replace `__FILL IN__` markers in the description.
- Write the "When to apply" section.
- Add `## Rules — <Topic>` sections as you add rules.

### New rule

```bash
tools/new-rule.sh python PY-001 "src/ layout vs flat layout"
```

This:

- Appends a four-part stub to `references/py.md` (or creates it).
- Adds a one-liner to `SKILL.md`'s rule index.

Then edit the four sections (What / Why / How / When NOT to apply)
following the structure above.

### After adding rules

Always run:

```bash
tools/render-index.sh   # regenerate INDEX.md
tools/lint.sh           # verify before committing
```

## Cross-skill references

Use plain relative markdown links:

```markdown
See [`UV-007`](../containers-best-practices/references/uv-python.md#uv-007)
in `containers-best-practices` for the container-side equivalent.
```

In a real skill, write same-skill asset links with a `./` prefix
so the marketplace's `bin/lint-skills.py`
verifies them too. `tools/lint.sh` checks that the linked path exists; it does **not**
check that the anchor resolves (anchors are case-folded and
hyphen-normalized in GitHub-flavored markdown).

## What lint enforces

`tools/lint.sh` exits non-zero on:

1. **Rule ID format** — anything not `^[A-Z]{2,7}-[0-9]{3,}$`.
2. **Rule ID duplication within a skill** — two `## SAME-ID` headers.
3. **Orphaned rule** — `## RULE-NNN` in references but not in SKILL.md index.
4. **Missing rule** — entry in SKILL.md index without a `## RULE-NNN` header in references.
5. **Dead link** — local markdown link to a non-existent path.
6. **Frontmatter format** — missing `name:` / `description:`, or description starting with first/second person.

Cross-skill prefix collisions emit a warning (not a failure) — same
prefix in two skills is suspicious but allowed if intentional.

## When generating content in-session

The agent should follow this skill's structure exactly when:

- Asked to "add a rule for X".
- Asked to "write a new best-practices skill for Y".
- Editing an existing rule entry.
- Drafting a SKILL.md description.

If unsure about scope (which prefix? which topic file?) ask the user
before writing — the wrong prefix is harder to fix after the rule
ships than asking up front.

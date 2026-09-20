# Best-practices library — conventions

This is the canonical format spec for every skill in the
`best-practices` module. Human-readable companion to
[`skills/meta-best-practices/SKILL.md`](skills/meta-best-practices/SKILL.md),
which is the same content shaped for in-session use by the agent.

If you're about to add a new rule, a new reference file, or a new
domain skill, read this first.

---

## Library shape

```
skills/<domain>-best-practices/
├── SKILL.md                      # entry point: description + scope + rule index
└── references/
    ├── <topic>.md                # detailed rule entries, keyed by rule ID
    ├── <topic>.md
    └── ...
```

- **One skill per domain.** A "domain" is roughly "the body of practice
  for one tool, language, or ecosystem" — `containers`, `uv`,
  `python`, `frontend`. Cross-domain content lives in whichever domain
  it leans toward, with markdown cross-links the other way.
- **`SKILL.md` is lean.** It carries the YAML frontmatter, a short
  "when to apply" section, and the **rule index** — a flat list of
  rule IDs with one-line summaries. No long-form prose.
- **`references/` carries the detail.** Each reference file holds a
  set of related rule entries in the canonical four-part shape (below).
  Reference files are read on-demand, not eagerly.

## Rule IDs

Format: `<PREFIX>-<NNN>` where `<PREFIX>` is an uppercase
domain-or-topic tag and `<NNN>` is a zero-padded sequence number.

```
DOCKER-001          # containers, Dockerfile-authoring topic
COMPOSE-014         # containers, compose topic
SEC-019             # containers, security-and-build topic
UVP-010             # uv-best-practices, project-shape topic
PY-022              # python-best-practices, linting topic
FE-040              # frontend-best-practices, a11y topic
```

### Rules for the prefix

- Uppercase letters only, 2–7 chars. Letters can stand for the domain
  (`PY`), a sub-topic within a domain (`COMPOSE`), or both. Be
  consistent within a skill.
- A skill can have multiple prefixes if it has clearly separated
  topics. The `containers-best-practices` skill uses `DOCKER`, `DEVC`,
  `COMPOSE`, `BUILDX`, `SEC`, `UV` — each for a different reference
  file. This is fine.
- A new skill that doesn't already exist picks one or more new
  prefixes; don't reuse a prefix that already exists in another skill.

### Rules for the number

- Zero-padded to 3 digits (`001` not `1`). Allows up to 999 rules per
  prefix before you have to grow to 4 digits.
- Sequential within a prefix. Gaps are allowed (deprecated rules) but
  reuse is not — once `DOCKER-018` is published, never resurrect that
  number with a different rule.
- Number assignment is first-come-first-served. The lint script
  enforces uniqueness within a skill.

## Severity scale

Every rule has an implicit severity used in audit / scan tooling and
in the discussion when the agent proposes fixes. The scale is:

| Severity | Meaning |
|---|---|
| **high** | Active security risk, real data-loss risk, or silently-broken behavior that ships to production. |
| **medium** | Bloat, cache misbehavior, observable performance regression, or a likely-but-not-certain failure mode. |
| **low** | Quality-of-life, readability, or hygienic — the project keeps working without fixing it, but it's a real improvement. |
| **needs-judgment** | Rule may or may not apply depending on context the agent can't determine from the file alone. Surface as a question, not a finding. |

Severity is **not** stored in the rule entry itself. It's assigned by
audit skills (like `containers-audit`) based on the rule and the
context. Two reasons:

1. The same rule can be high-severity in production and low-severity
   in a throwaway dev container — context decides.
2. Storing severity in the rule entry creates drift between the rule
   and the audit's severity table.

The audit skill for each domain owns the severity mapping for the
rules in that domain.

## Reference-file rule entry shape

Every rule in `references/*.md` follows this exact four-part
structure:

```markdown
## RULE-NNN — One-line title

**What.** Restate the rule precisely, in one paragraph at most.

**Why.** A concrete failure mode if you violate it — real footgun, not
theory. Cite a CVE, a documented incident, an upstream bug, or a
named consequence ("the cache is silently wiped after every install").

**How.** A minimal correct snippet. Real code that compiles and runs,
not pseudocode. If multiple correct approaches exist, show the
simplest one and mention alternatives in prose.

**When NOT to apply.** Exceptions and trade-offs. Always include this
section. If a rule has no real exceptions, write "Never. <reason>."
explicitly rather than omitting the section.
```

Notes:

- **Heading is exactly two `#`s.** This is what the lint script
  matches when verifying that every `SKILL.md` rule index entry has a
  corresponding reference entry.
- **`What/Why/How/When NOT to apply` are bold-prefixed paragraphs**,
  not subheadings. Subheadings would inflate the markdown TOC for
  little gain.
- **No "TODO" or "WIP" markers in published rules.** A rule that's
  not ready stays in draft until it is. Stubs are fine in
  `references/*.md` when scaffolding a new skill, but they should be
  whole-file stubs ("This reference file is a stub; rules forthcoming")
  rather than half-written rule entries.

## `SKILL.md` shape

Every domain skill's `SKILL.md` follows this skeleton:

```markdown
---
name: <domain>-best-practices
description: <third-person sentence with strong trigger keywords. Mention the file types, tools, and prompts that should activate this skill.>
---

# <Domain> best practices

A curated rule set for <one-sentence scope>. Each rule has a stable
ID and a one-line summary. Full **What / Why / How / When-not-to-apply**
entries live in `references/`.

## When to apply this skill

Activate when any of these are true:

- <Specific trigger 1 — file types, tool names, prompts>
- <Specific trigger 2>
- ...

## How to use the rule index

1. Scan the relevant section(s) below for rule IDs that apply to the current file.
2. For each rule you intend to apply or flag, open the corresponding `references/` file and read **only that rule's entry** — they're keyed by ID.
3. Cite the rule ID when you explain a change to the user.

## Rules — <Topic 1>

See [`references/<topic1>.md`](references/<topic1>.md).

- **PREFIX-001** — One-line summary.
- **PREFIX-002** — One-line summary.
- ...

## Rules — <Topic 2>

See [`references/<topic2>.md`](references/<topic2>.md).

- **PREFIX-010** — One-line summary.
- ...
```

The `description:` field is the most load-bearing thing in the file —
it's what the harness matches against user prompts to decide whether to
activate the skill. See "Description-field rules" below.

## Description-field rules

Skills auto-activate based on a fuzzy match between the user's
current context and the skill's `description:` field. A bad
description means the skill silently never triggers; a too-broad
description means it fires on unrelated prompts.

Rules:

1. **Third person.** "Use when …" / "Activate on …" — never "I" or "you."
2. **Lead with concrete triggers.** File types, tool names, command
   names — things that literally appear in the user's prompt or the
   files the agent is reading. Avoid vague descriptors ("modern", "best
   practices for code quality").
3. **Mention the rule prefixes.** Helps the agent reach for the right
   skill when the user mentions a specific rule ID.
4. **Be specific about scope.** If the skill is "uv as a Python
   project tool," say so — "uv usage outside of containers." That
   distinguishes it from the container-uv content.
5. **No marketing language.** "comprehensive", "ultimate", "essential"
   are noise. Trigger keywords are signal.

Good description (containers):

> Use when working with Dockerfiles, docker-compose, buildx, or dev
> containers (devcontainer.json). Covers DOCKER-, COMPOSE-, DEVC-,
> BUILDX-, SEC-, UV- rule families …

Bad description:

> Comprehensive best practices for modern containerization workflows.

The first will fire when a user pastes a Dockerfile or asks about
compose. The second will fire on… nothing in particular.

## Adding a new rule

```bash
# from the module root (modules/best-practices/)
tools/new-rule.sh containers DOCKER-027 "title of the rule"
```

This appends a four-part stub to the appropriate reference file
(deduced from the prefix, or asked interactively) and inserts the
one-liner into `SKILL.md`'s rule index. Fill in the four sections.

## Adding a new domain skill

```bash
# from the module root
tools/new-skill.sh <domain>
```

Creates `skills/<domain>-best-practices/{SKILL.md, references/}` with
the SKILL.md scaffold filled out. Edit the `description:`,
"when to apply" section, and the rule-index sections.

## Cross-skill references

Use plain relative markdown links:

```markdown
See [UVP-040](../../uv-best-practices/references/python-versions.md#uvp-040)
in `uv-best-practices` for the project-level rule.
```

`tools/lint.sh` verifies these resolve.

## What the lint script enforces

Run `tools/lint.sh` from the module root. It fails on:

1. **Rule ID format violation** — anything not matching `^[A-Z]{2,7}-\d{3,}$`.
2. **Rule ID collision within a skill** — two `## RULE-001` headers under the same skill.
3. **Orphaned rule entry** — a `## RULE-NNN` header in `references/*.md` that's not listed in the parent `SKILL.md` rule index.
4. **Missing rule entry** — a rule ID in the `SKILL.md` rule index that has no matching `## RULE-NNN` header in `references/*.md`.
5. **Dead cross-skill link** — a `[...](...)` link pointing to a path that doesn't exist.
6. **Frontmatter format** — `name:` and `description:` fields present; `description:` is third-person heuristic check (doesn't start with "I", "You", "This skill").

Run `tools/lint.sh` before every PR; the marketplace's `bin/check.sh` is
the CI gate and does not invoke it.

## What `tools/render-index.sh` produces

Generates `INDEX.md` at the module root — a flat table of every rule
across every skill, with anchor links into the reference files.
Re-run after adding rules:

```bash
tools/render-index.sh
git add INDEX.md
```

`INDEX.md` is checked in (so it's browsable on GitHub) but is treated
as generated — never edit it by hand.

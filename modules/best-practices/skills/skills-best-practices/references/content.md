# SKILL content rules

Detailed entries for `SKILL-010..SKILL-015` — how the instructions in a
skill are written. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

## Contents

- SKILL-010 — Degree of freedom matches fragility
- SKILL-011 — One default, not a menu
- SKILL-012 — No time-conditional instructions
- SKILL-013 — One term per concept
- SKILL-014 — Output templates with stated strictness
- SKILL-015 — Concrete input/output examples

---

## SKILL-010 — Degree of freedom matches fragility

**What.** Choose how prescriptive each instruction is from how fragile the
task is:

- **High freedom** (prose heuristics) when several approaches are valid
  and the right one depends on context — a code review.
- **Medium freedom** (a template or parameterized script) when a
  preferred pattern exists but variation is fine — a report generator.
- **Low freedom** (an exact command, no parameters) when the operation is
  fragile, consistency is critical, or a sequence must be followed — a
  database migration.

**Why.** The guide's analogy: an open field needs only a direction; a
narrow bridge with cliffs on both sides needs guardrails. Exact commands
on a judgment task make the model follow steps that do not fit the case;
loose prose on a fragile task lets it improvise a flag or skip a step
where any deviation breaks the result.

**How.**

```markdown
## Database migration

Run exactly this script:

    python scripts/migrate.py --verify --backup

Do not modify the command or add flags.
```

**When NOT to apply.** Never as a principle; the judgment is in placing
each instruction on the scale.

---

## SKILL-011 — One default, not a menu

**What.** When several tools or approaches could work, name one default
and give an explicit escape hatch for the case it does not cover. Do not
list equivalent alternatives.

**Why.** "Use pypdf, or pdfplumber, or PyMuPDF, or pdf2image…" hands the
choice back to the model with no basis to make it, so it varies from run
to run and may pick the option least suited to the case. A default plus a
named exception gives one consistent path and still covers the edge case.

**How.**

```markdown
Use pdfplumber for text extraction.
For scanned PDFs that need OCR, use pdf2image with pytesseract instead.
```

**When NOT to apply.** When the right choice genuinely depends on context
only the user has (a licensing constraint, a platform), name the deciding
factor for each option rather than listing them flat.

---

## SKILL-012 — No time-conditional instructions

**What.** Do not write instructions that depend on the current date ("if
before August 2025, use the old API"). Document the current method as the
main path, and move superseded methods into a collapsed "old patterns"
section with the date they were deprecated.

**Why.** A skill outlives the moment it was written, and the model cannot
reliably know today's date in relation to the cutoff. A date condition
turns wrong silently once the date passes, and nothing in the skill
signals that it went stale.

**How.**

```markdown
## Current method

Use the v2 endpoint: api.example.com/v2/messages

## Old patterns

<details>
<summary>Legacy v1 API (deprecated 2025-08)</summary>
The v1 endpoint api.example.com/v1/messages is no longer supported.
</details>
```

**When NOT to apply.** Never. A dated record of *when* something changed
is fine; an instruction that *branches* on the date is not.

---

## SKILL-013 — One term per concept

**What.** Choose one word for each concept and use it throughout the
skill: always "API endpoint", always "field", always "extract".

**Why.** Mixing "API endpoint", "URL", "API route" and "path" for one
thing makes the model wonder whether they are different things, and an
instruction written with one synonym may not be connected to a rule
written with another. Consistent terms make instructions easier to parse
and follow.

**How.**

```text
Good: field … field … field
Bad:  field … box … element … control
```

**When NOT to apply.** Never inside one skill. When the user's domain has
a fixed term, use that term rather than inventing one.

---

## SKILL-014 — Output templates with stated strictness

**What.** When the output has a required shape, give a template and say
how strictly to follow it: "ALWAYS use this exact structure" for machine-
consumed output (API responses, data formats), or "a sensible default —
adapt sections to the analysis" for documents where judgment helps.

**Why.** Without a template the shape drifts between runs; with a template
but no stated strictness, the model either forces a rigid shape onto a
case that needs adapting, or loosens a format a downstream parser depends
on.

**How.**

```markdown
## Report structure

ALWAYS use this exact template:

# [Analysis title]
## Executive summary
[One-paragraph overview]
## Key findings
- Finding with supporting data
## Recommendations
1. Specific, actionable recommendation
```

**When NOT to apply.** Free-form outputs (an explanation, a conversation
answer) need no template.

---

## SKILL-015 — Concrete input/output examples

**What.** When output quality depends on style — commit messages, naming,
tone — give two or three concrete input/output pairs, followed by a
one-line statement of the pattern they share. Examples are real-looking
cases, never placeholders such as "Input: X, Output: Y".

**Why.** Examples convey style and level of detail more clearly than a
description of them does, the same as in ordinary prompting. Abstract
examples show the format but not the judgment.

**How.**

```markdown
**Example 1**
Input: Added user authentication with JWT tokens
Output: feat(auth): implement JWT-based authentication

**Example 2**
Input: Fixed dates displaying incorrectly in reports
Output: fix(reports): correct date formatting in timezone conversion

Follow this style: type(scope): brief description.
```

**When NOT to apply.** When the output has one correct form that a
template (SKILL-014) or a script (SKILL-021) already fixes, examples add
tokens without adding information.

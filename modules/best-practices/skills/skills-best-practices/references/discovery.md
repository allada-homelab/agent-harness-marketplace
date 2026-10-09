# SKILL discovery rules

Detailed entries for `SKILL-001..SKILL-004` — the `name` and
`description` frontmatter, which is all the harness preloads to decide
whether a skill fires. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

## Contents

- SKILL-001 — `name`: 64 characters, lowercase-hyphen, no reserved words
- SKILL-002 — One consistent naming pattern
- SKILL-003 — `description` says what and when
- SKILL-004 — Third person in the `description`

---

## SKILL-001 — `name`: 64 characters, lowercase-hyphen, no reserved words

**What.** The `name` field is at most 64 characters, uses only lowercase
letters, digits and hyphens, contains no XML tags, and does not contain the
reserved words `anthropic` or `claude`.

**Why.** These are validation rules in Anthropic's skill format, not style:
a skill that breaks them is rejected at upload rather than loading with a
warning. Harnesses that read the skill from disk are often more lenient, so
a non-conforming name can work locally for months and then fail the day the
skill is published to the API or claude.ai.

**How.**

```yaml
---
name: processing-pdfs
description: …
---
```

Not `name: Claude_PDF_Helper` — uppercase, underscore and a reserved word.

**When NOT to apply.** Never for the character limits and alphabet. A
harness can add its own constraints on top (for example, a requirement
that `name` equals the directory name); follow both.

---

## SKILL-002 — One consistent naming pattern; nothing vague or generic

**What.** Name every skill in a collection with the same pattern. The guide
prefers the gerund form (`processing-pdfs`, `analyzing-spreadsheets`);
noun phrases (`pdf-processing`) and action forms (`process-pdfs`) are
acceptable when a collection already uses them. Avoid vague names
(`helper`, `utils`, `tools`) and generic ones (`documents`, `data`,
`files`).

**Why.** The name is what users and other skills cite, and it sits beside
the description in the preloaded metadata. A vague name gives the model
and the reader nothing to discriminate on, and a collection that mixes
patterns is harder to search and to reference correctly.

**How.**

```text
Good:  processing-pdfs, analyzing-spreadsheets, writing-documentation
Avoid: helper, utils, data, my-stuff
```

**When NOT to apply.** An existing collection with its own convention
keeps it — consistency inside the collection outranks the gerund
preference. (This library names its skills `<domain>-best-practices` for
that reason.)

---

## SKILL-003 — `description` says what *and* when, in the prompt's own terms

**What.** The description states what the skill does and when to use it,
and names the concrete terms a matching prompt or file contains: file
types, tool names, command names, error symptoms. It is non-empty, at most
1,024 characters, and contains no XML tags.

**Why.** The description is the only part of a skill the model sees before
choosing it — it picks from potentially 100+ skills by matching the task
against these lines. A description that says only *what* ("Processes
data") gives no trigger to match; one without the literal terms users type
("PDF", ".xlsx", "commit message") is skipped when it should fire.

**How.**

```yaml
description: Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction.
```

Not `description: Helps with documents`.

**When NOT to apply.** Never. Keep it tight as well as specific: some
harnesses send every skill's description on every request, so each extra
clause is a recurring token cost paid on every turn, not only when the
skill fires.

---

## SKILL-004 — Third person in the `description`

**What.** Write the description in the third person ("Processes Excel
files…", "Use when…"). Never "I can help you…" or "You can use this to…".

**Why.** The description is injected into the system prompt next to every
other skill's. The guide warns that an inconsistent point of view there
causes discovery problems: the model reads first- and second-person text
as a voice in the conversation rather than as a catalog entry.

**How.**

```yaml
description: Generate descriptive commit messages by analyzing git diffs. Use when the user asks for help writing commit messages or reviewing staged changes.
```

**When NOT to apply.** Never. The body of `SKILL.md` can address the
model directly ("Run the validator…"); this rule covers the description
only.

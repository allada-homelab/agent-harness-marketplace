# SKILL structure rules

Detailed entries for `SKILL-005..SKILL-009` — concision and progressive
disclosure: what goes in `SKILL.md`, what goes in bundled files, and how
the model finds them. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

## Contents

- SKILL-005 — Only context the model lacks
- SKILL-006 — `SKILL.md` body under 500 lines
- SKILL-007 — References one level deep
- SKILL-008 — Table of contents in long reference files
- SKILL-009 — Descriptive names, domain layout, forward slashes

---

## SKILL-005 — Only context the model lacks

**What.** Assume the model is already capable. For every paragraph, ask
whether the model needs it, whether it can be assumed known, and whether
it justifies its token cost. Cut explanations of general concepts (what a
PDF is, how libraries are installed) and keep the project-specific facts,
choices and commands.

**Why.** Once a skill loads, every token in it competes with the system
prompt, the conversation history and the user's actual request for the
same context window. The guide's PDF example says the same thing in ~50
tokens (a library choice and three lines of code) that a verbose version
spends ~150 on, and the extra 100 carry nothing the model did not know.

**How.**

```markdown
## Extract PDF text

Use pdfplumber for text extraction:

    import pdfplumber
    with pdfplumber.open("file.pdf") as pdf:
        text = pdf.pages[0].extract_text()
```

**When NOT to apply.** When testing shows a weaker model tier needs the
extra explanation (SKILL-025), keep it — but keep it because a test
failed without it, not by default.

---

## SKILL-006 — `SKILL.md` body under 500 lines

**What.** Keep the `SKILL.md` body under 500 lines. When it approaches
that, move detail into separate files in the skill directory that
`SKILL.md` names, each loaded only when the task needs it (progressive
disclosure). Organize the split as a high-level guide with references, by
domain (one file per dataset or area), or as basic content with links to
advanced cases.

**Why.** Only `name` and `description` are preloaded; `SKILL.md` is read
in full when the skill fires; other bundled files cost nothing until
read. Content left in `SKILL.md` is paid for on every activation even when
the task needs one section of it. The guide gives 500 lines as the
threshold for optimal performance.

**How.**

```markdown
# BigQuery data analysis

## Available datasets

**Finance**: revenue, ARR, billing — see reference/finance.md
**Sales**: opportunities, pipeline — see reference/sales.md
```

A sales question loads `reference/sales.md` and nothing else.

**When NOT to apply.** A short skill that fits comfortably in one file
should stay one file; splitting it adds a read with nothing saved.

---

## SKILL-007 — References one level deep

**What.** Every bundled reference file is linked directly from
`SKILL.md`. A reference file does not send the model on to another file
for the content it needs.

**Why.** The guide observes that the model may only partially read a file
reached through another referenced file — previewing it with something
like `head -100` instead of reading it whole — and then works from
incomplete information. A chain `SKILL.md` → `advanced.md` →
`details.md` puts the actual content at the depth most likely to be
skimmed.

**How.**

```markdown
# SKILL.md

**Basic usage**: [instructions here]
**Advanced features**: see advanced.md
**API reference**: see reference.md
**Examples**: see examples.md
```

**When NOT to apply.** A reference file may cross-link a sibling for
optional background, as long as everything the task needs is reachable
from `SKILL.md` in one hop.

---

## SKILL-008 — Table of contents in long reference files

**What.** A reference file longer than 100 lines opens with a short list
of its sections.

**Why.** When the model previews a file with a partial read, a table of
contents at the top still shows it the file's full scope, so it can read
the whole file or jump to the section it needs instead of concluding the
first screen is all there is.

**How.**

```markdown
# API reference

## Contents
- Authentication and setup
- Core methods (create, read, update, delete)
- Error handling patterns

## Authentication and setup
…
```

**When NOT to apply.** Files under ~100 lines, which a preview already
shows in full.

---

## SKILL-009 — Descriptive names, domain layout, forward slashes

**What.** Name bundled files for what they hold
(`form_validation_rules.md`, not `doc2.md`), group them by domain or
feature (`reference/finance.md`, `reference/sales.md`), and write every
path with forward slashes.

**Why.** The model navigates a skill directory like a filesystem: a file
name is the only signal it has before opening the file, so `docs/file1.md`
costs a read to discover what a descriptive name would have said.
Backslash paths (`scripts\helper.py`) fail on Unix systems, while forward
slashes work everywhere.

**How.**

```text
bigquery-skill/
  SKILL.md
  reference/
    finance.md
    sales.md
  scripts/
    validate_query.py
```

**When NOT to apply.** Never for forward slashes. Naming and layout
follow the conventions of the collection the skill ships in when it has
them.

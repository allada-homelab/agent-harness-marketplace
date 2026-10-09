# SKILL evaluation rules

Detailed entries for `SKILL-024..SKILL-026` — proving a skill helps, and
improving it from observed behavior. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

## Contents

- SKILL-024 — Evaluations and a baseline before extensive content
- SKILL-025 — Test with every model tier that will run it
- SKILL-026 — Iterate from a fresh agent's real behavior

---

## SKILL-024 — Evaluations and a baseline before extensive content

**What.** Before writing much of the skill:

1. Run the model on representative tasks *without* the skill and record
   the specific failures and missing context.
2. Turn those gaps into at least three evaluation scenarios, each with a
   query, its input files and the expected behaviors.
3. Measure the no-skill baseline on them.
4. Write only enough instructions to close the gaps and pass.
5. Re-run, compare against the baseline, and refine.

**Why.** A skill written before anyone watched the model fail documents
imagined problems: it spends tokens on what the model already does well
and can miss what it actually gets wrong. Without a baseline there is no
evidence the skill changes anything. The guide notes there is no built-in
runner — the evaluations themselves are the source of truth.

**How.**

```json
{
  "skills": ["processing-pdfs"],
  "query": "Extract all text from this PDF and save it to output.txt",
  "files": ["test-files/document.pdf"],
  "expected_behavior": [
    "Reads the PDF with a suitable PDF library or command-line tool",
    "Extracts text from every page without missing any",
    "Saves the text to output.txt in a readable format"
  ]
}
```

**When NOT to apply.** A skill that only packages a fixed reference (a
schema, a style guide) with no behavior to change still needs trigger
tests (SKILL-026), even when a behavioral baseline adds little.

---

## SKILL-025 — Test with every model tier that will run it

**What.** Run the evaluations on each model the skill will be used with.
Check that a smaller, faster tier gets enough guidance, that a mid tier
finds the skill clear and efficient, and that the strongest tier is not
over-instructed.

**Why.** A skill adds to a model; it does not replace one. What works for
the strongest tier can leave a small tier without the step it needed, and
detail a small tier needs can make the strongest one slower and more
literal. A skill tested on one tier is verified on that tier only.

**How.**

```text
for model in <fast tier> <balanced tier> <strongest tier>:
    run all evaluations with the skill loaded
    record pass/fail per expected behavior
```

**When NOT to apply.** A skill pinned to one model (for example, a forked
skill that always runs on a fixed tier) needs testing on that tier only.

---

## SKILL-026 — Iterate from a fresh agent's real behavior

**What.** Develop with two instances: one helps you write and refine the
skill, and a fresh one with only the skill loaded does real tasks. Watch
the fresh one and bring what you see back to the first:

- **Triggering** — does the skill fire on the prompts it should, and stay
  quiet on the ones it should not? Fix the `name` and `description` first.
- **Unexpected paths** — does it read files in an order you did not
  intend? The structure is less clear than it looks.
- **Missed connections** — does it fail to follow a reference to a file it
  needed? Make the link more explicit.
- **Over-reliance** — does it read the same bundled file every time? That
  content may belong in `SKILL.md`.
- **Ignored content** — does it never open a bundled file? It may be
  unneeded or badly signposted.

**Why.** The author already knows what the skill means, so reading it back
cannot reveal what a model without that context does with it. Real usage
shows the gaps — a rule the agent skipped because it was not prominent, a
file it never found — and changes based on observation fix them, where
changes based on assumptions often do not.

**How.**

```text
Observation: asked for a regional sales report, the agent wrote the query
but did not filter out test accounts, although the skill mentions it.
Change: move the rule to the top of the workflow as "MUST filter test
accounts", then re-run the same task on a fresh agent.
```

**When NOT to apply.** Never. Even a skill that passes its evaluations
should be watched in real use, because evaluations only cover the cases
someone thought to write.

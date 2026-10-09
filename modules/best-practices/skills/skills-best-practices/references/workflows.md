# SKILL workflow rules

Detailed entries for `SKILL-016..SKILL-018` — multi-step tasks and the
validation loops that keep them correct. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

## Contents

- SKILL-016 — Numbered steps, a copyable checklist, explicit branches
- SKILL-017 — Feedback loop: validate, fix, re-validate
- SKILL-018 — Plan-validate-execute for risky operations

---

## SKILL-016 — Numbered steps, a copyable checklist, explicit branches

**What.** Break a complex task into numbered, sequential steps. For a
long workflow, give a checklist the model copies into its response and
checks off as it goes. Where the path depends on the case ("creating new
content?" / "editing existing content?"), make each branch an explicit
labeled sub-workflow. When a workflow grows large, move it into its own
file and tell the model which file to read for which task.

**Why.** Clear steps keep the model from skipping a validation step in
the middle of a long task, and a visible checklist lets both the model
and the user see what is done. Implicit branching leaves the model to
infer which instructions apply, and it can blend the two paths.

**How.**

```markdown
## Form-filling workflow

Copy this checklist and check off items as you complete them:

- [ ] Step 1: Analyze the form (run analyze_form.py)
- [ ] Step 2: Create the field mapping (edit fields.json)
- [ ] Step 3: Validate the mapping (run validate_fields.py)
- [ ] Step 4: Fill the form (run fill_form.py)
- [ ] Step 5: Verify the output (run verify_output.py)

If verification fails, return to Step 2.
```

**When NOT to apply.** Single-step or judgment-only tasks (SKILL-010,
high freedom) need no checklist.

---

## SKILL-017 — Feedback loop: validate, fix, re-validate

**What.** For quality-critical work, build the loop into the
instructions: run a validator, fix what it reports, run it again, and
proceed only on a pass. The validator can be a script or a reference
document the model checks its work against (a style guide, a checklist).

**Why.** The guide calls this pattern one that greatly improves output
quality: a validation step that runs only once (or only at the end) lets
an early error flow into everything built on it, while an explicit "only
proceed when validation passes" gate catches it where it is cheap to fix.

**How.**

```markdown
## Document editing process

1. Edit word/document.xml.
2. Validate immediately: python ooxml/scripts/validate.py unpacked_dir/
3. If validation fails: read the error, fix the XML, validate again.
4. Only proceed when validation passes.
5. Rebuild: python ooxml/scripts/pack.py unpacked_dir/ output.docx
```

**When NOT to apply.** When nothing can check the output objectively,
say so and ask for review instead of inventing a validator that always
passes.

---

## SKILL-018 — Plan-validate-execute for risky operations

**What.** For batch operations, destructive changes, complex validation
rules or other high-stakes work, have the model first write its intended
changes to a structured plan file (for example `changes.json`), validate
that file with a script, and only then apply it: analyze → create plan →
validate plan → execute → verify.

**Why.** Asked to update 50 form fields from a spreadsheet in one step,
the model can reference fields that do not exist, set conflicting values
or miss required ones, and the damage is applied before anything checks
it. A plan file is machine-verifiable, can be revised without touching the
originals, and turns errors into specific messages before any change
lands.

**How.**

```text
1. python scripts/analyze_form.py input.pdf > fields.json
2. Write the intended updates to changes.json.
3. python scripts/validate_changes.py fields.json changes.json
   → "Field 'signature_date' not found. Available fields:
      customer_name, order_total, signature_date_signed"
4. Fix changes.json until validation passes.
5. python scripts/apply_changes.py input.pdf changes.json output.pdf
```

Make the validator's messages specific — name the bad value and the valid
options — so the model can fix the plan without guessing.

**When NOT to apply.** Small, easily reversed edits do not need a plan
file; the overhead outweighs the risk.

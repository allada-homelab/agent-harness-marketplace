# plan-for-dummies

Write an implementation plan that a less capable model (Sonnet, Haiku, a cheap
subagent) will execute without the planner present.

Two failure modes, opposite directions: a plan that compresses decisions into
verbs ("follow the existing pattern", "handle errors appropriately"), and a plan
so long the implementer cannot hold it or the planner spent longer writing it
than the task would take. The rule is **make every decision, write as little as
possible** — aim under ~50 lines, shorter than the diff it produces, no function
bodies, no line numbers, two to four checkpoints with real expected output.

Generic guardrails (never weaken a test, stop rather than work around, paste real
output) live once in the implementer's standing instructions, not in every plan.

## Contents

- `skills/plan-for-dummies/SKILL.md` — the method, budget, writing rules, plan
  template, and the standing-guardrails block.
- `skills/plan-for-dummies/references/before-and-after.md` — one task written
  the bloated way and the right way.

## History

0.1.0 was an add-only method calibrated for a reader that could not explore.
A nine-ticket run produced 23,000 lines of plans that were no more checkable for
it. 0.2.0 is a from-scratch rewrite.

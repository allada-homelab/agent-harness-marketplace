# plan-for-dummies

Scope and plan a coding task so that a **less capable model** can implement it
without your context or judgment.

The skill exists to prevent one specific failure: a strong model writes the plan
it would execute itself — steps compressed into verbs like "wire up" and
"refactor accordingly", assuming the implementer can explore the codebase, infer
conventions, and recover from surprises. A weaker implementer can't, so it
improvises, and that is where the damage happens.

The guiding rule: anything the planner had to look up, run, or reason about, the
implementer would have to redo — worse. Put the result in the plan instead.

## Contents

- `skills/plan-for-dummies/SKILL.md` — the workflow: pin the task, explore and
  verify by actually running things, make every decision, write the plan, grade
  the risk, self-review as the implementer, write reviewer notes.
- `skills/plan-for-dummies/references/plan-template.md` — the plan structure the
  skill produces, plus the reviewer-notes template.

## Output

A self-contained plan file (default `PLAN.md`) and reviewer notes — never an
implementation.

## Harnesses

Portable prose with no harness-specific keys, so Claude Code, pi and dsh all
load it.

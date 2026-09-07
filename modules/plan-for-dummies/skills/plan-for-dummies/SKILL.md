---
name: plan-for-dummies
description: Scope and plan a coding task so that a less capable model can implement it without your context or judgment. Use this whenever the user asks for a plan, spec, or implementation guide that will be handed to another model, a "weaker" or "cheaper" model, a subagent, or a junior implementer — or says things like "plan this for Sonnet/Haiku/a local model to implement", "write the plan, something else will do the work", "scope this out for handoff", or "I'll review it after". Also use it when the user just says "write a plan" in a workflow where you know planning and implementation are split. The output is a self-contained plan file plus reviewer notes, not an implementation.
---

# Plan for Dummies

You are writing a plan that a **less capable model** will execute. It will not have this conversation, will not have your judgment, and will not be able to ask you questions. Everything it needs has to be in the document.

The core failure this skill exists to prevent: a strong model writes the plan it would execute itself. Its steps compress real work into verbs like "wire up", "handle", "refactor accordingly", and assume the implementer can explore the codebase, infer conventions, notice conflicts, and recover from surprises. A weaker model can't do those things reliably, and when it hits a gap it improvises — which is where the damage happens.

The guiding rule: **anything you had to look up, run, or reason about to write this plan, the implementer will have to redo, worse. Put the result in the plan instead.**

## Who you are writing for

Hold this picture in mind throughout: a careful contractor who has never seen this codebase, cannot ask questions, and will do exactly what is written — no more, no less. It is fine at mechanical edits, following exact commands, and filling in code around a skeleton you provide. It is unreliable at exploration, inferring conventions, choosing between alternatives, recognizing when it is done, recognizing when something has gone wrong, and staying in scope.

Also remember that a stronger model (probably you, later) will review the result. The plan's job is not to prevent every mistake; it is to make mistakes cheap to find and to make the implementer's deviations visible.

## Workflow

### 1. Pin down the task

Confirm you understand the goal, the reason behind it (briefly — enough to disambiguate, not enough to invite creativity), and the boundaries. If the user's request is ambiguous in a way that would change the plan, ask now. Ambiguity that survives into the plan becomes a decision the implementer makes badly.

Ask the user how the plan will be handed over if you don't already know: whole plan at once, or one step at a time. This affects how much you restate per step (see Handoff modes).

### 2. Explore and verify — actually run things

Do the discovery work yourself and record the results. Reading about the codebase is not enough; the plan must contain facts you have confirmed, because your own guesses have the same hallucination risk as the implementer's.

Concretely:

- Read the files that will be touched. Record exact paths, the relevant line ranges, and paste in the actual signatures, types, and call sites — don't summarize them.
- Identify the repo's conventions and write them as rules: where new modules go, naming patterns, how errors are wrapped, how tests are organized, lint/format commands, commit conventions.
- Check installed library versions and quote real method signatures from `node_modules`, site-packages, or equivalent. Weaker models confidently invent APIs; give them the real one.
- Run the test suite, lint, and any build or e2e commands from a clean shell. Record the exact commands, required setup (env vars, services, migrations, seed data), how long they take, what a passing run looks like (paste the tail of real output), and any pre-existing failures so the implementer doesn't try to fix them or panic.
- Figure out how to run a single test or a subset. The implementer should iterate on what it just touched, not the whole suite.
- Determine whether e2e is runnable in the implementer's environment at all. If it needs credentials, network, or a browser the implementer won't have, say so and mark those checks reviewer-only.

If exploration reveals the task is larger, riskier, or differently shaped than the user described, go back to them before writing the plan.

### 3. Make every decision

Every fork in the plan is a place the implementer can go wrong. Resolve them all before writing:

- Pick the approach, the data structures, the names, the file locations. State them flatly. No "choose an appropriate...", no "either X or Y works", no "consider...".
- Write the hard parts as code, not prose: interfaces, type definitions, the tricky algorithm, the regex, the SQL query, the migration. Anything that requires judgment gets written out by you; the implementer does mechanical fill-in around it.
- Write the tests, or at least the test cases with inputs and expected outputs. Acceptance criteria should be executable, not described.
- Decide what is out of scope and write it down as explicit non-goals. Weaker models both under- and over-do; naming what not to touch is as important as naming what to change.

### 4. Write the plan

Use the structure in `references/plan-template.md`. Read it before writing. The sections exist for specific reasons:

- **Context and goal** — because the implementer has none of this conversation.
- **Non-goals and forbidden moves** — because scope creep and bad recovery moves (deleting failing tests, `// @ts-ignore`, widening to `any`, `--no-verify`, commenting out assertions) are the most common ways a weak implementer turns a small task into a mess.
- **Runbook** — because the implementer will otherwise run `npm test`, hit a missing env var, and start editing test files.
- **Pre-flight checks** — so the implementer confirms the world matches the plan before changing anything, and stops if it doesn't.
- **Steps** — small enough that each is independently verifiable, ordered so a failure is localized, each with its own check and stop conditions.
- **Success criteria** — in three layers (per-step, integration, regression) plus negative criteria, split into implementer-verified and reviewer-verified.
- **Report template** — so the handoff back is structured around the plan rather than a paragraph of self-assessment.

Style rules that matter more than usual:

- Name things exactly. Not "the handler" — `handleLogin` in `src/auth/login.ts`. Not "the config" — `config/default.yaml`, key `auth.timeout`.
- Avoid pronouns and back-references that point at earlier steps. If the implementer's context gets truncated, "as above" points at nothing.
- Prefer commands with expected output over descriptions of outcomes. "The endpoint returns the user's orders" is a description; `curl -s localhost:8000/orders/42 | jq '.[0].id'` printing `1001` is a criterion.
- Where you can't make a criterion executable, write it as observable behavior — given / when / then — not intent.
- Prefer "stop and report" over "figure it out". When the plan meets reality that doesn't match, the implementer's default should be to halt, not improvise.
- Include the *why* only where it disambiguates. Reasons that invite the implementer to second-guess the plan are worse than no reasons.

### 5. Grade the risk and pad the risky parts

After the first draft, go through each step and estimate how likely a weak implementer is to get it wrong, and how expensive that would be to detect and fix. Mark each step low / medium / high.

Then allocate effort unevenly:

- **High-risk steps** get more: an intermediate check before proceeding, more of the code written out, an explicit "before continuing, confirm X and Y" gate, a throwaway script that exercises just that piece, and a list of the specific ways it tends to go wrong.
- **Low-risk steps** (boilerplate, mechanical edits the reviewer will catch instantly if wrong) get a single check and can be specified more loosely. Over-specifying these wastes your effort without helping.

The rule for where to spend tokens: specify tightly where errors are expensive or hard to spot in review; specify loosely where they are obvious and cheap.

The risk grades also feed the reviewer notes (step 7).

### 6. Self-review as the implementer

Reread the entire plan as the contractor described above. At every point where that person would have to:

- (a) look something up,
- (b) make a choice, or
- (c) guess what a word or reference means,

flag it and fix it in the plan. Do not leave notes like "implementer should determine..." — resolve it yourself. Also check that no step depends on knowledge from this conversation that isn't written down, and that every file, function, and command named in the plan actually exists (you verified them in step 2).

### 7. Write the reviewer notes and report template

The same strong model that planned this will review the result, so write it a message. Keep this in a separate section (or separate file, if the user prefers the implementer not see it) with:

- A short preamble: what the task was, the key tradeoffs you made and why, and what you are worried about. This lets the review start from intent instead of reconstructing it from the diff.
- Where to look: the high-risk steps and the specific corner-cutting you expect there ("Step 4 is where I'd expect thin error handling — check the catch block"; "if `schema.sql` was touched, that's wrong").
- Which success criteria are reviewer-only and how to check them.

Tell the implementer to leave a trail: one commit per step with the step number in the message, no squashing, so the reviewer can bisect to the step where things went sideways. The report template in the plan should ask, per step: what was done, the check output pasted verbatim, and any deviation from the plan and why. Deviations are the single most important thing for the reviewer, and weak models bury them — make the template force them out.

## Handoff modes

**Whole plan at once.** The runbook, conventions, and forbidden moves can live once at the top. Steps can be shorter. Still avoid back-references within steps; restating a file path is cheap.

**One step at a time.** Each step must be self-sufficient: restate the relevant runbook commands, the files involved, the forbidden moves that apply, and the check. Assume the implementer sees only the preamble and the current step. Tell the implementer explicitly not to read ahead or do anything beyond the current step.

If you don't know which mode will be used, write for step-at-a-time; it degrades gracefully to whole-plan.

## Output

Write the plan to a file (default `PLAN.md` in the repo root, or wherever the user's workflow expects it) and tell the user the path. If reviewer notes are meant to be hidden from the implementer, write them to a sibling file (`PLAN.review.md`). Do not begin implementing. Do not summarize the plan back in chat beyond a few sentences; the file is the deliverable.

Before handing it over, sanity-check the plan's length against the task. A three-file change that produces a 900-line plan is probably over-specifying boilerplate; a twelve-file change in a 200-line plan is almost certainly compressing work into verbs again.

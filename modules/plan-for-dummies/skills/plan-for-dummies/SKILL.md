---
name: plan-for-dummies
description: Write an implementation plan that a less capable model (Sonnet, Haiku, a cheap subagent) will execute without the planner present. Use this whenever the user asks for a plan, spec, task breakdown, or handoff that "the implementer", a subagent, or a weaker/cheaper/smaller model will carry out — even if they don't say "for a weaker model." Also use when a plan will be executed in a separate session, or when the user mentions a planner/implementer/reviewer split.
---

# Plan for Dummies

You are the strong model. A weaker one will execute what you write, and you won't be there to answer questions. Later a strong model reviews the result.

## The two failure modes

When you plan for yourself you compress: "follow the existing pattern", "handle errors appropriately", "add tests". Each is a decision you trust yourself to make at execution time. A weaker model makes it too — confidently and often wrongly.

The opposite failure is just as real: a plan that takes longer to write than the task, or is too long for the implementer to hold in mind. Delegation exists to save the strong model's time.

So: **make every decision, but write as little as possible.** Spend words only where a wrong interpretation is plausible.

## Budget

- Aim for under ~50 lines. If you're heading well past that, the task should split or you're over-specifying.
- The plan should be shorter than the diff it produces. If not, do the task yourself.
- Write it once, front to back. Skim for ambiguity at the end; don't rewrite.
- Never write a function body. Literal code only for interfaces: signatures, schemas, config keys, error strings.
- Refer to code by file path and symbol name (`src/api/search.py`, `search_handler`), never by line number — lines drift.

## Before writing

**Is it delegable?** Tasks needing judgment throughout (open-ended debugging, design exploration) aren't. Do the exploratory part yourself, then delegate the mechanical remainder. Say so to the user.

**Investigate to sufficiency.** Open the files. Stop once you can name every file that will change and every decision can be made. Put the answers in the plan:
- Exact paths, function names, signatures, config keys, and the test command.
- The existing code to mirror — point at it by file and symbol. Paste a snippet only when there's a plausible *wrong* thing nearby.
- Anything surprising you hit (similarly named files, a second config, an ordering gotcha). These become "Watch out" lines.
- Where a step depends on a library or framework API, name the library and the exact version in use (check the lockfile) and tell the implementer to look up the docs for that version before writing the call. Weaker models default to whatever API shape they remember, which is often a different major version.

**Zero open decisions.** Scan for *TBD, consider, decide whether, or similar, could, might, either*. Each is a decision pushed onto a weaker model. If you can't decide, ask the user — never the implementer.

## Writing rules

- **No vague words.** "Appropriately", "as needed", "etc.", "similar to", "clean up", "handle edge cases", "best practices" — each hides an unmade decision. Write the decision.
- **One line per mechanical step.** `Add upload_rate_limit_per_min: int = 10 to Settings in src/settings.py.` Only steps where a wrong move is plausible get more: what to change, and one "Watch out" naming the wrong move.
- **Checkpoints, not per-step verification.** Two to four points in the plan with a command and expected result.
- **A "why" only where it prevents a specific misstep.** Too much rationale invites the implementer to reason its way to a different answer.
- **Task-specific guardrails only.** Generic ones (don't weaken tests, stop rather than work around) live in a standing file — see below — not in every plan.

## Template

```markdown
# Plan: <title>

## Goal
One or two sentences: what's true when done that isn't now.

## Read first
- `path/to/file.py` — `some_function`, the pattern you'll mirror.
- Docs: <library> <exact version> — <the specific API or page>. Read before step N.

## Out of scope (this task)
- <task-specific only>

## Stop if
- <task-specific only, e.g. "`search_handler` doesn't use `@rate_limited`">

## Steps
1. <one line>
2. <one line>
   Checkpoint: `<command>` → `<expected>`
3. <riskier step: what to change; literal code only if it's an interface>
   Watch out: <the plausible wrong move>
   Checkpoint: `<command>` → `<expected>`

## Done when
- `<command>` → `<expected>`
- Only these files changed: <list>

## Report back
Files changed / commands run with pasted output / deviations / unsure about.
```

Drop sections that are empty for this task. Always keep Done-when and Report-back. Save the plan to a file; the implementer will re-read it mid-task. The implementer's prompt is just: "Follow this plan exactly, fill in Report back, stop where it says to stop."

## Standing guardrails

Put these once in the implementer's instruction file or system prompt; never repeat them in a plan. Offer to create the file if the user doesn't have one.

```markdown
- Follow the plan exactly. No features, options, abstractions, refactors, or dependencies it doesn't list.
- Never delete, skip, or weaken a test. No broad except/catch, type-ignore, or lint-disable. Mock nothing the plan didn't name.
- If something isn't as the plan describes, or a checkpoint fails and the fix isn't in the plan: stop, fill in Report back, end. Stopping is good; working around is bad.
- Paste real command output in the report. "Tests pass" without output is not acceptable.
```

## Final skim

Read the plan as the implementer. For each line: could it be read two ways? does it need a lookup I haven't given? a decision I haven't made? Fix those. Then: would deleting this line cause a plausible wrong outcome? If not, cut it.

For the reviewer: Done-when is the rubric, "only these files changed" catches drift in one `git diff --stat`, and the report's deviations line is where to look first.

See `references/before-and-after.md` for one task written both ways.

# Plan template

Use this structure. Sections may be omitted only when they would be empty for a real reason (e.g. no e2e exists), and then say so explicitly rather than leaving the section out silently — the implementer should never wonder whether something was forgotten.

Text in `[brackets]` is guidance; replace it. Everything else is literal scaffolding the implementer should see.

---

````markdown
# Plan: [short task name]

## Read this first

You are implementing this plan exactly as written. Do not add features, refactor
adjacent code, or "improve" anything not named here. If something in this plan
does not match what you find in the repository, or a check fails and the plan does
not say what to do about it, STOP and report using the template at the bottom.
Do not guess and do not work around it.

[If step-at-a-time mode:] Implement only the step you have been given. Do not read
ahead. Do not begin the next step until told to.

Commit after every step with the message `Step N: <step title>`. Do not squash.

## Context

[3–8 sentences. What this codebase is, what the relevant subsystem does today,
and what is wrong or missing. Only what is needed to make the steps unambiguous.]

## Goal

[One or two sentences. What is true when this task is done.]

## Non-goals

Do NOT:
- [Do not modify `path/to/file` — list every file/area that is off limits]
- [Do not refactor / rename / reformat anything not named in a step]
- [Do not add dependencies]
- [Do not change the signature of `fn` in `path`]
- [Do not "fix" the pre-existing test failures listed in the Runbook]

## Forbidden recovery moves

If something fails, you may NOT:
- Delete, skip, or comment out a failing test or assertion
- Add `// @ts-ignore`, `# type: ignore`, `as any`, `unknown` casts, or widen types to make errors go away
- Use `--no-verify`, `--force`, or bypass hooks
- Change a config or environment setting not named in this plan
- [Repo-specific additions]

Instead: stop and report.

## Environment and conventions

- Language/runtime: [e.g. Node 20.11, TypeScript 5.4 — verified with `node -v`]
- Package manager: [e.g. pnpm 9 — use `pnpm`, not `npm`]
- Relevant installed libraries and versions: [name@version, with the real signature
  of any API the steps rely on, copied from the installed package]
- Where new files go: [exact directory and naming pattern, with an existing example]
- Error handling convention: [with a pasted example from the repo]
- Formatting/lint: [command]; run before every commit
- [Other conventions the steps depend on]

## Runbook

All commands run from the repo root unless stated.

### One-time setup
```bash
[exact commands, in order: env vars, services, migrations, seed data]
```

### Run a single test file
```bash
[exact command with a placeholder path]
```

### Run the full test suite
```bash
[exact command]
```
Takes ~[N] minutes. Do not interrupt it.

Expected passing output ends with:
```
[paste the real tail of a passing run]
```

Known pre-existing failures (ignore these; do not fix them):
- [test name and file, or "none"]

### Lint / typecheck
```bash
[exact commands]
```

### End-to-end
[Either: exact commands, setup, duration, expected output —
 or: "Not runnable in your environment (requires X). Reviewer will run it." —
 or: "This repo has no e2e."]

## Pre-flight checks

Run these before changing anything. If any does not match, STOP and report.

1. `git status` shows a clean working tree.
2. `[full test command]` passes with only the known pre-existing failures.
3. `[file]` exists and line [N] reads: `[exact line]`
4. [Any other assumption the plan relies on, as a checkable command]

## Steps

[Repeat for each step. Small enough to verify independently. Ordered so a failure
is localized. Restate file paths in every step — never "the file from step 2".]

### Step 1: [Imperative title]

**Risk:** [low | medium | high] — [one clause on why, e.g. "touches shared types"]

**Files:**
- `path/to/file.ts` (modify, lines ~40–65)
- `path/to/new_file.ts` (create)

**Change:**

[Precise description of the edit. For anything requiring judgment, give the code:]

```ts
[exact code to add / replace, with enough surrounding context to locate it]
```

[For low-risk mechanical edits a precise prose description is fine. For medium
and high risk, prefer code.]

**Before continuing, confirm:** [high-risk steps only — an intermediate gate]
```bash
[command]
```
Expected: [exact output or exit code]

**Check:**
```bash
[command that verifies this step in isolation]
```
Expected: [exact output]

**Stop if:**
- [specific condition — e.g. "the check prints anything other than the expected
  output", "the file does not contain `[anchor string]`", "a test other than
  `[test name]` fails"]

**Commit:** `Step 1: [title]`

---

[...more steps...]

## Success criteria

### Verified by you (the implementer)

Per-step checks: all "Check" blocks above pass.

Integration:
```bash
[command exercising the whole change end to end]
```
Expected: [exact output]

Regression:
```bash
[full test suite command]
```
Expected: passes with only the known pre-existing failures listed in the Runbook.

```bash
[lint / typecheck command]
```
Expected: exit 0.

Negative criteria (things that must NOT have happened):
```bash
git diff --stat main -- .
```
Expected: only these paths appear: [list]. Any other path is a failure.
- No new dependencies in `[package.json / requirements / etc.]`
- `[protected file]` unchanged: `git diff main -- [path]` prints nothing
- [Others]

### Verified by the reviewer (do not attempt; just report)

- [Criteria the implementer cannot reliably judge: design quality, whether the
  abstraction is right, anything requiring e2e in an environment it lacks]

## Report

When finished (or when stopping early), reply with exactly this structure:

```
## Status
[COMPLETE | STOPPED AT STEP N]

## Pre-flight
[paste output of each pre-flight check]

## Steps
### Step 1: [title]
Done: [what you changed, one or two sentences]
Check output:
[paste verbatim]
Deviations from plan: [NONE, or exactly what you did differently and why]

### Step 2: ...

## Success criteria
[for each implementer-verified criterion: PASS/FAIL and the pasted output]

## Reviewer-only criteria
[list them; do not assess]

## Anything unexpected
[anything you noticed that the plan did not anticipate, even if you did not act on it]
```
````

---

# Reviewer notes

Write these for the strong model that will review the implementation. Put them in
a separate section at the end of the plan, or in a sibling file
(`PLAN.review.md`) if the user does not want the implementer to see them.

````markdown
# Reviewer notes: [task name]

## What this was
[2–4 sentences: the task, the approach chosen, the main alternatives rejected and why.]

## What I'm worried about
[The high- and medium-risk steps, and the specific failure you expect at each:
"Step 4: expect the catch block to swallow errors — verify it rethrows."
"Step 6: if `schema.sql` was touched, that is wrong; the plan uses a code-level default."]

## How to review efficiently
- Commits are one per step; bisect by step number if something is off.
- Read the Deviations lines in the report first.
- [Anything else: "diff should touch only these N files", "run e2e with `...`"]

## Reviewer-only criteria
[Repeat the list with how to check each.]
````

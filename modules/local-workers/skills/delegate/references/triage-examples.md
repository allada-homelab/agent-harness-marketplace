# Triage examples: scale-out vs reason-out

Worked cases for deciding, after an opt-in, whether a piece goes to `pi-run` or stays with you.

## Scale-out (delegate)

The common property: a competent junior with clear instructions could do it, and you can check the
result by inspection.

- **Search and exploration** (`pi-run --read-only`): "find every file in `src/` that imports
  `lodash`"; "for each component in `apps/web/components/`, which use the deprecated `useOldStore`
  hook"; "summarize what each file in `src/utils/` does, one line each".
- **Mechanical edits** (`pi-run`): "rename `getUserById` to `findUserById` across the backend
  (~25 call sites)"; "add docstrings to the exported functions in `dates.ts` and `strings.ts`";
  "replace `console.log` with `logger.info` in `apps/api/src/`".
- **Batch commands** (`pi-run`): "run each package's unit tests and report which pass"; "run
  `tsc --noEmit` for each `apps/*` and list the ones with errors".
- **Classification and summary**: "tag these 30 tickets bug / feature / chore" — a fixed question
  over many records is `decide`'s job; "summarize the last 10 commits" is `pi-run --read-only`.
- **Spec-driven coding** (`pi-run`): "write tests for `parseDate` in `src/utils/date.ts` covering
  ISO strings, Unix timestamps and invalid input, following `string.test.ts`"; "implement the
  `RetryClient` described in `docs/retry-spec.md`, with its tests".

## Reason-out (keep, even after an opt-in)

Success rests on judgement, and a confident wrong answer would mislead David. Delegate the
discovery sub-steps, not the conclusion.

- Debugging the unfamiliar: a test that flakes only in CI; latency that doubled after a deploy.
- Architecture and design: tokens vs sessions for a new app; a multi-tenant schema.
- Security and correctness review: IDOR in an endpoint; an auth middleware bypass.
- Tradeoffs: cache this query or not; Postgres vs DynamoDB for one table.
- Inference across unrelated parts: stale data after a release that changed the cache, the schema
  and a flag at once.
- Anything where "good enough" isn't: hot-path production code, money, auth, PII, irreversible
  migrations.

## Borderline cases

1. **"Add error handling to this function."** If you can write the spec in two sentences ("wrap
   the X call in try/except, return `Result` like `foo.py`"), delegate it. If not, keep it.
2. **"Refactor this module to be cleaner."** Keep the design; delegate the discovery ("list every
   external caller and what it passes in").
3. **"Fix the failing tests."** Run them once yourself first. A mechanical cause (an intended
   snapshot change, a renamed symbol) can be delegated; a real regression stays with you.
4. **"Write a script that does X."** Delegate when X is well defined; keep it when the workflow
   itself needs designing.
5. **"Review this PR."** Mechanical checks (tests present, style followed, tests pass) can go out
   in parallel; "is this the right design?" stays.
6. **"Investigate why this is slow."** Delegate the measurement ("profile it, report the top 10
   functions by self-time"); reason about the numbers yourself.
7. **"Apply the same fix to the other 12 services."** Delegate — after you have validated the fix
   once yourself, or you scale out a bug.

## Common mistakes

- **Delegating before you know what good looks like.** Do one yourself, then delegate the rest.
- **Delegating below the size floor.** A single `grep` is not worth a run.
- **Forgetting to batch.** Three independent runs go out in one message, not one after another.
- **Re-sending a failed brief unchanged.** Same brief, same outcome: re-brief or escalate.

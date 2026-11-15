---
name: replay-eval
description: >-
  Benchmark the local model on David's own codebase by replaying already-merged fixes — check out the commit before a fix, re-implement it with pi-run from the issue alone, and grade the result against the merged change as ground truth (MATCH / PARTIAL / MISS). Use when David asks to evaluate, benchmark or replay-test the local model or pi on real fixes, or to re-check the capability map after the model behind large-default changes.
argument-hint: "<merged PR number, fix commit, or \"last N\">"
user-invocable: true
harness: [claude]
---

# replay-eval

An objective benchmark for local delegation on David's code: re-solve a ticket that was already
solved, from the commit before its fix, and compare what the local model produces with the solution
that actually merged. Passing gates only shows the change is self-consistent; grading against the
merged fix shows whether the model reached the *right* solution.

**This is an eval, not work.** It never pushes, opens a PR or merges — it stops at a graded diff.

Targets: $ARGUMENTS — a PR or commit David names, or "last N" for the last N merged fixes
(`git log --first-parent --grep fix --oneline`). With none given, ask which fixes to replay.

## Cardinal rule

**No worker ever sees the merged fix.** It is the answer key. Brief every run from the issue's
requirements only; read the reference patch yourself, and only at the grading step. A worker that has
seen the merged diff makes the result worthless.

## Procedure

1. **Scratch area.** Keep every run artifact in a scratch directory outside the repo.
2. **Reference (for grading only):** `git show <fix-commit> > <scratch>/reference-<id>.patch`.
3. **Baseline checkout:** a throwaway local clone at the commit before the fix —
   `git clone -q --no-hardlinks <repo> <scratch>/replay-<id>` then
   `git -C <scratch>/replay-<id> checkout -q <fix-commit>^`. **Freshness check:** confirm the gap
   exists at the baseline (the bug reproduces, or the code lacks the change). If it doesn't, the
   baseline is wrong — stop.
4. **Re-implement from the issue only.** Read the original issue (`gh issue view`, or the ticket
   text) — never the reference — and implement it with `pi-run` inside the clone, following the
   `delegate` skill (or the `complete-tasks-mixed-tier` loop). Gate every run on the artifact
   (`git diff`, exit code, a real test run), never on pi's report. Record one line per run in
   `<scratch>/runs-<id>.tsv`: piece, worker (`pi-run`, or `escalated:sonnet` …), attempt, outcome,
   failure reason (`gate_fail`, `fabricated_success`, `timeout`, `scope_wander`, `bad_diff`), seconds,
   and the pi session id.
5. **Grade against ground truth.** Save the produced diff, then read the reference and judge
   *functional* equivalence, not textual:
   - **MATCH** — meets the same acceptance criteria by an equivalent approach.
   - **PARTIAL** — works, but misses something the reference covered (an edge case, a test, a
     touched file, a second-order break).
   - **MISS** — wrong or incomplete.
6. **Report** per target: gate outcome, grade and the delta from ground truth; then the aggregate —
   unaided vs escalated rate, the top failure modes, and any row of
   `../delegate/references/capability-map.md` the results contradict. Delete the scratch clones.

## What it reliably surfaces

Fabricated success over an empty diff, thinner test coverage than the human's, and missed blast
radius (the pre-existing test a fix breaks). Grading catches all three where a bare gate would not.

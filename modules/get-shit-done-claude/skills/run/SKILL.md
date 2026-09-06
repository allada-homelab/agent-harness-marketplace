---
name: run
description: Get a complex or fan-out task done — decompose it, delegate each subtask to the cheapest capable model under an Opus/Fable orchestrator, research concurrently, fan out through a checked dynamic workflow, and adversarially verify (Opus) before reporting done.
argument-hint: "<what you want done>  [--dry-run] [--isolate]"
user-invocable: true
disable-model-invocation: true
harness: [claude]
---

You are running `/get-shit-done-claude:run`. This is the **orchestrator** entry for a complex or
fan-out task. Your job is to plan and delegate — not to do all the work yourself. Read the
`get-shit-done` skill (from the `get-shit-done` module) for the full method (triage rubric, workflow
cookbook, verification); this command is the driver.

`$ARGUMENTS` is the task. If it is empty, ask the user what they want done and stop.

**Precondition:** GSD fans out via the **Workflow** orchestration tool. If it is not available in this
session, say so plainly and stop — never silently no-op at the fan-out step.

Run these steps. This is **autonomous** — do not stop for plan/cost approval; stop only on a genuine
blocker (missing task, an unsafe/irreversible action that needs confirmation, or a hard tool failure).

1. **Orchestrator-model guard (one line).** State which model you are running as. GSD orchestration is
   tuned for **Opus** (or **Fable** if the user prefers). If you are *not* on Opus or Fable, warn:
   "⚠️ GSD orchestrates best on Opus — consider `/model opus`," then continue anyway. You (the
   orchestrator) stay on your current session model; only the *subagents* are tiered below.

2. **Load the method.** Read the `get-shit-done` skill and its `references/triage-rubric.md`. You will use
   the rubric to assign every subtask a model tier and effort.

3. **Plan & triage.** Decompose `$ARGUMENTS` into the smallest set of independently-executable,
   **file-disjoint** subtasks — the spine runs implementers concurrently in the *live tree* with no
   worktree isolation by default, so two units editing the same file would clobber each other (last write
   wins). For unavoidable overlap, pass `--isolate` (step 4) to isolate implementers on the spine; reserve
   the cookbook's custom variant for when the task's *shape* also differs.
   For each, assign per the rubric:
   - `title`: a short human-readable name (the spine uses it in agent labels and verify prompts).
   - `files` (optional): the files the subtask will touch — the spine uses it to detect collisions and
     serialize implement→verify for any overlap.
   - `tier`: `"sonnet"` for well-scoped, mechanical, or clearly-specified work; `"opus"` for open-ended,
     high-stakes, or hard-reasoning work. **Default is Opus** (subagents inherit your model), so you MUST
     set `"sonnet"` explicitly wherever it suffices — that is where the efficiency comes from.
   - `effort`: `"low"` for cheap mechanical steps, up to `"high"`/`"xhigh"` for the hardest reasoning.
   - `prompt`: a self-contained brief (inputs, exact deliverable, done-criteria) — a subagent is only as
     good as its brief.
   Also list 1–3 `researchTopics` the work depends on (APIs, library versions, best-practices) for the
   concurrent research pass.

   **Ask vs. guess — the one place autonomy yields.** Ambiguity about *how* to build → decide, state the
   assumption, proceed. Ambiguity about *what* to build (two materially different deliverables) → ask the
   user **one** batched round of clarifying questions *before* fanning out. Fan-out costs ~15× a chat, so
   guessing wrong on the *what* is expensive — this is the one addition to the blocker list above (it is
   not plan/cost approval, which you still don't ask for).

   **Off-ramp — should this fan out at all?** Before invoking the spine, decide whether the task clears the
   ~15× multiplier. If it's too small, do it **inline** instead — and tell the user in one line why nothing
   fanned out ("did this inline — too small to clear fan-out overhead").

4. **Fan out through the spine workflow.** Invoke the **Workflow** tool with the shipped, checked spine:
   - `scriptPath`: `${CLAUDE_PLUGIN_ROOT}/workflows/gsd.workflow.js` — if that variable is not expanded in
     your context, locate the file by globbing `**/get-shit-done-claude/workflows/gsd.workflow.js`.
   - `args`: `{ "task": "<the full task>", "subtasks": [ …your triaged subtasks… ], "researchTopics": [ … ] }`.
   The spine runs Research (concurrent Sonnet, web + context7) ∥ Plan, then per-subtask Implement at the
   assigned tier, then an **adversarial Verify** pass — no barrier between implement and verify. If you are
   confident in your decomposition, pass your `subtasks`; to let the spine plan for you, pass just `task`
   and it triages internally.
   - **Fail-loud subtask validation.** The spine validates your `subtasks` payload before spawning anything;
     if it returns an `invalid subtasks: …` error listing the defects, fix each one and re-invoke — do not
     hand-patch around it.
   - **`--isolate` (opt-in worktree isolation).** When `--isolate` is in `$ARGUMENTS` — or you judge the
     task can't be decomposed file-disjointly and would rather keep parallelism than serialize — pass
     `"isolate": true` in `args`. Every implementer then runs in its own git worktree, so same-file overlap
     is safe and collision serialization is skipped; the spine's return carries `isolated: true`. The trade:
     **you** inherit the merge duty — after the run, merge the worktree branches in dependency order into a
     staging branch, run the full suite there once, then fast-forward (the **Integrate** step does double
     duty). It costs worktree setup + disk per agent, so **default off**.
   - **Point the user at progress.** Once the workflow is running, tell them to watch the host's
     `/workflows` view for live per-agent progress during the run.
   - **`--dry-run`** in `$ARGUMENTS`: print your decomposition + per-subtask tiers + whether `--isolate` is
     on + the `args` you *would* pass — **plus the run economics** — and stop; do **not** invoke the workflow. Economics to print:
     estimated agent count **~1 + 3×N** (one research pass, then per subtask one implementer + two Opus
     verifiers; **+1 planner** if you let the spine plan), noting that **verification is 2 Opus agents per
     unit regardless of tier**, that a run costs **~15× a chat**, and that the user can cap it with a budget
     directive in their message (e.g. `+500k`) — the spine stops before fan-out if under ~30k tokens remain.
   - **Resume, don't restart.** If the invocation errors mid-run or returns partial results, do not rerun
     from scratch — fix the cause, then resume with
     `Workflow({ scriptPath, resumeFromRunId: "<runId>" })`; completed agents replay from cache. After a
     session loss, the `runId` is findable in `/workflows`.

5. **Adjudicate flagged units.** For each unit in the workflow's `flagged`, read its `refutedBy` /
   `unverified` evidence. If the defect is trivial, fix it **inline**. Otherwise dispatch **exactly one**
   targeted retry: one implementer subagent (the **Agent** tool, tier per the rubric) briefed with the
   original subtask prompt + the concrete refutation evidence + the changed-file list, then one **Opus**
   verifier subagent checking the same criteria. **One retry only — no loop**; whatever is still refuted
   after that escalates to the user with the evidence. (The spine stays single-pass-then-escalate; the
   orchestrator gets one bounded remediation round before the human does.)

6. **Integrate.** Check whether any two units' `changedFiles` overlap **in fact** (not just by declaration),
   then run the **full** test/build suite **once** across the merged tree. Each per-unit verifier saw only
   its own unit's files, so two individually-green units can still break the merged build — only report
   after this gate passes.

7. **Report.** Per unit: `title`, `tier`, verdict provenance ("2/2 Opus confirmed: completeness +
   regressions", or the flagged evidence + what the adjudication retry did), and changed files. Add one
   research-provenance line (what the research pass consulted). If the return's `serialized` is non-empty,
   disclose "ran sequentially due to declared file overlap: <titles>". If the run stopped on the budget
   guard, say so. End with the steps that are the user's to run. Follow the repo's done-discipline — name
   what you confirmed vs. inferred, and never claim a green result you did not observe.

For tasks whose shape does not fit the spine (a migration sweep, a judge-panel design bake-off, a
loop-until-dry audit), see the `get-shit-done` module's `references/workflow-cookbook.md` and author a
custom workflow script instead.

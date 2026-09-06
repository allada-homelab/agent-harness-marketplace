---
name: get-shit-done
description: >-
  Method for getting a complex or fan-out software task done by orchestrating
  subagents — decompose the task, delegate each subtask to the cheapest capable
  model (Sonnet for well-scoped work, Opus for hard reasoning) under an
  Opus/Fable orchestrator, run concurrent Sonnet research (web + context7), fan
  out through a checked dynamic workflow, and adversarially verify before done.
  Use when the user wants to implement,
  build, migrate, or refactor something big enough to warrant decomposition and
  parallel fan-out. Explains the triage rubric (which tier per subtask), the
  workflow cookbook (authoring fan-out), and the verification gate.
---

# Get Shit Done — orchestrating complex & fan-out work

You are the **orchestrator** (Opus, or Fable if the user prefers). Your job is to *plan and delegate*,
then *integrate and verify* — not to do all the work inline. The heavy lifting fans out to subagents
tiered by complexity, over a checked spine workflow, with an always-on Opus adversarial verify pass.

On Claude Code, the `get-shit-done-claude` module's `/get-shit-done-claude:run <task>` drives this flow
with the Workflow tool. On other harnesses, run the steps below with whatever subagent facility the
harness has, or sequentially.

## When to use this — and when not to

**Use it** when the task is big enough to earn decomposition: implementing a feature end-to-end, a
multi-file migration or refactor, a broad audit, anything with independent parallelizable pieces.

**Don't fan out** when the work is small, or has real **sequential dependencies**, or shares evolving
context across pieces (if fixing one thing might fix another, or two units would edit the same code). Most
coding tasks have fewer truly parallel pieces than they look. For those, a single focused agent (or just
doing it inline) beats fan-out — parallelizing a dependency chain produces wasted or broken work. Fan-out
pays on **breadth-first, low-dependency** work, and it costs ~15× a chat, so only fan out when the task's
value clears that. When you take the off-ramp and do it inline, say so in one line ("did this inline — too
small to clear fan-out overhead") so the user knows nothing fanned out.

## The loop

1. **Orchestrator-model guard.** State your model. GSD is tuned for Opus (or Fable). If you're on
   anything else, warn (`/model opus`) and continue — only subagents tier down; you stay put.
2. **Plan & triage.** Decompose the task into the smallest set of **independently-executable, file-disjoint**
   subtasks. Front-load ambiguity *now* (an ambiguous brief handed down-tier comes back wrong-shaped).
   Ambiguity about *how* to build → decide and proceed; ambiguity about *what* to build (two materially
   different deliverables) → ask **one** batched round *before* fanning out (guessing wrong on the *what*
   costs ~15× a chat). For each subtask write a self-contained brief — a `title`, inputs, exact deliverable,
   done-criteria, an explicit *what NOT to touch*, and optionally the `files` it will touch (the spine
   serializes any overlap) — then assign `tier` + `effort` per **`references/triage-rubric.md`**. Remember:
   **subagents inherit Opus** unless you set `"sonnet"` explicitly — that override is where the efficiency
   lives.
3. **Fan out.** Run Research (concurrent, web + docs lookup) ∥ Plan, then per-subtask Implement at the
   assigned tier, then an adversarial Verify pass — pipelined, no barrier between implement and verify. On
   Claude Code, the `get-shit-done-claude` module's `/get-shit-done-claude:run` drives this with the
   Workflow tool: it validates your `subtasks` payload first — title/prompt nonempty, `tier` sonnet|opus,
   `effort` in the enum, `files` an array of strings — and returns an `invalid subtasks: …` error listing
   every defect instead of running; fix them and re-invoke. Elsewhere, run the steps with whatever
   subagent facility the harness has, or sequentially. When the units **can't** be made file-disjoint, the
   escape hatch is worktree isolation: every implementer gets its own git worktree, overlap-serialization
   is skipped, and **you** then merge the worktree branches in dependency order and run the full suite on
   the merged result. It costs a worktree per agent — default off.
4. **Adjudicate flagged units.** For each unit in `flagged`, read its `refutedBy`/`unverified` evidence.
   Trivial defect → fix inline; otherwise dispatch **exactly one** evidence-briefed retry (one implementer
   at the rubric's tier, then one Opus verifier on the same criteria). One retry only — whatever is still
   refuted escalates to the user with the evidence. The spine stays single-pass; you get one bounded round.
5. **Integrate.** After the workflow returns, *your* job is integration, not more delegation: read every
   result, check whether any two units' `changedFiles` overlap **in fact** (not just by declaration), and
   run the **full** test/build suite once across the merged result — per-unit green checks don't prove a
   conflict-free whole.
6. **Report honestly.** Per unit: `title`, `tier`, verdict provenance ("2/2 Opus confirmed: completeness +
   regressions", or the flagged evidence + what the retry did), and changed files; one research-provenance
   line; if `serialized` is non-empty, disclose "ran sequentially due to declared file overlap"; if the run
   stopped on the budget guard, say so. End with the steps that are the user's to run. Name what you
   confirmed vs. inferred; never claim a green result you didn't observe.

This is **autonomous** — no plan/cost-approval gate. Stop only on a genuine blocker: a missing task, an
unsafe/irreversible action needing confirmation, or a hard tool failure. (`--dry-run` prints the plan
without spawning.)

## Delegate by complexity (the efficiency engine)

The validated pattern is a strong orchestrator over cheaper workers (Opus-lead + Sonnet-subagents beat
single-agent Opus by ~90% on Anthropic's eval). Route each subtask by three signals — **specifiability**,
**output verifiability**, and **task type** — and tune **effort before reaching for a bigger model**. Full
rubric with worked examples: **`references/triage-rubric.md`**. The one rule you can't skip: set
`tier: "sonnet"` *explicitly*, or it silently runs on Opus.

## Concurrent research (dogfood web + context7)

The spine's Research phase runs Sonnet agents that pull current docs and best-practices via WebSearch and
context7 (resolved through ToolSearch), concurrently with planning (it feeds Implement, so it's a
concurrent prerequisite, not fire-and-forget), and feeds a compact summary into the
implementer prompts. Treat those findings as **trust-but-verify** — an implementer confirms a load-bearing
claim against the real API before relying on it. If the project has an llm-wiki bundle
(`<project>/llm-wiki/index.md`), the research phase reads it **first** — curated project-specific knowledge beats
generic web results (the spine's research prompt does this when the bundle exists).

## Adversarial verification (always on)

Every implemented unit is checked by **two independent Opus** verifiers before it counts as done (the gate
is where correctness is decided, so it always gets the strongest critic — even for Sonnet-tier work). Keep
the critics **independent**: each sees the requirements + the implementer's changed-file list, **never its
narrative or reasoning trace**, and inspects the real changes rather than trusting the self-report. The two
run **distinct lenses** — one checks *completeness* against the brief, the other checks *regressions &
side-effects* beyond the listed files. Each returns a three-state verdict: `confirmed`, `refuted` (concrete
evidence of a defect), or `couldnt_verify` (couldn't positively confirm — not a refutation). Confirmation
requires **two live positive verdicts**; **any** refutation, any `couldnt_verify`, or a dead verifier
withholds "confirmed" and flags the unit for you to adjudicate — a lone skeptic is enough, because
confident-but-wrong output survives lenient majority votes. It's single-pass-then-escalate: no
generator↔verifier refinement loop (which risks infinite back-and-forth or silent timeout-approval). For
richer checks, route the verify phase to a purpose-built reviewer (`pr-review-toolkit:code-reviewer`,
`silent-failure-hunter`) — see the cookbook.

## Utilize all tools

"Get it done" means composing the whole ecosystem, not reinventing it: `Explore` for codebase search,
`task-researcher`/context7/WebSearch for docs, the code-reviewer agents for verify, any session MCP tool
(reachable from workflow agents via ToolSearch), and existing skills (brainstorming, writing-plans) when
they fit. Inside a workflow, `agent(prompt, {agentType})` picks the right worker.

## Task shapes beyond the spine

For a migration sweep (parallel code mutation needs **git-worktree isolation** — parallel edits to one
tree clobber each other), a judge-panel design bake-off, or a loop-until-dry audit, author a custom
workflow script. Patterns, skeletons, and the Workflow authoring footguns are in
**`references/workflow-cookbook.md`**.

## Invocation modes

- **Explicit (default, always on):** on Claude Code, `/get-shit-done-claude:run <task>`; elsewhere, ask
  for this method by name.
- **Auto-trigger (shipped disabled):** on Claude Code, an optional hook nudges toward GSD when a prompt
  looks like fan-out work. See the `get-shit-done-claude` module for details.

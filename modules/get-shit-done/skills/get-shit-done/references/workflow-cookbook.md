# Workflow cookbook — authoring fan-out beyond the spine

The shipped spine (`workflows/gsd.workflow.js`) covers the common case: research ∥ plan → tiered
implement → adversarial verify. Reach for a **custom** workflow script only when a task's *shape*
doesn't fit that pipeline. Author it with the `Workflow` tool (`script` inline, or write a file and pass
`scriptPath`). This file is your reference for the shapes and the footguns.

## First: should you fan out at all?

Fan-out pays on **breadth-first, low-dependency** work — multi-file audits/migrations, independent
test-file fixes, multi-repo analysis (Anthropic measured up to 90% wall-clock reduction on breadth-first
research). It **hurts** on tasks with sequential dependencies or shared, evolving context: "most coding
tasks involve fewer truly parallelizable tasks than research." If fixing one thing might fix another, or
two units would edit the same code, do it **sequentially in one agent** instead.

- **Decompose by ownership boundary, not by file count.** Give each unit a functional domain, a
  self-contained brief (subagents don't inherit your conversation), and an explicit *what NOT to touch*.
- **Scale agent count to complexity.** ~2–4 concurrent coding agents is the practical ceiling; beyond
  that, review + merge overhead outweighs the speedup. Don't spawn 50 for a simple job.

## Workflow authoring footguns (these fail at *runtime*, mid-fan-out)

- `export const meta = {...}` must be a **pure literal** — no variables, calls, or interpolation. Its
  `phases` titles should match your `phase()` calls.
- **No `Date.now()` / `Math.random()` / argless `new Date()`** — they throw (they'd break resume). Vary
  agent prompts/labels by index; stamp timestamps after the workflow returns.
- **`pipeline()` is the default**, not `parallel()`. Use `parallel()` (a barrier) only when a stage
  genuinely needs *all* prior results at once (dedup/merge, early-exit on zero, cross-item comparison).
- **Set `{model: "sonnet"}` explicitly** on down-tier agents — they inherit Opus otherwise (see the
  triage rubric).
- **`schema`** forces structured output (validated at the tool layer, model retries on mismatch) — use it
  whenever you need to branch on a result.
- A thrown stage/thunk resolves to `null` — `.filter(Boolean)` before using results.
- Concurrency caps at ~10–16 agents at once; a single `parallel`/`pipeline` call takes ≤4096 items.
- Honor `budget` for scale: `while (budget.total && budget.remaining() > 50_000) {...}`.

## Route to the best worker, don't reinvent it

"Utilize all tools" — inside a workflow, `agent(prompt, {agentType: "..."})` uses a purpose-built
subagent instead of the generic one. Compose the ecosystem:

- **`Explore`** — broad read-only codebase search (find call sites, conventions) before you plan.
- **`task-researcher`** / **WebSearch** + **context7** (via ToolSearch) — external docs & best-practices.
- **`pr-review-toolkit:code-reviewer`**, **`feature-dev:code-reviewer`**, **`silent-failure-hunter`** —
  strong, purpose-built reviewers for the Verify phase.
- Any session MCP tool is reachable from a workflow agent via ToolSearch.

> These named agents (`pr-review-toolkit:*`, `feature-dev:*`, `task-researcher`, …) are **optional
> external plugins** — GSD doesn't declare them as dependencies. `agent({agentType})` against an
> uninstalled agent fails, so use them only "when they fit," and fall back to the default worker (a
> plain `agent(...)` with a strong brief) when a given plugin isn't present.

## Pattern: migration sweep (parallel code mutation → worktree isolation)

Parallel agents that **edit the same tree clobber each other — last write wins, silently.** Isolate each
in its own git worktree so conflicts defer to an explicit merge.

```js
export const meta = {
  name: 'migrate-sweep',
  description: 'Apply one transform across many files/modules, isolated per unit, verified',
  phases: [{ title: 'Discover' }, { title: 'Transform' }, { title: 'Verify' }],
}
phase('Discover')
const sites = await agent('List every module needing <transform>. Return {units:[{path,brief}]}.',
  { schema: SITES })                              // scout the work-list first
const done = await pipeline(sites.units,
  u => agent(`Apply <transform> to ${u.path}. ${u.brief}. Touch ONLY this module.`,
    { label: `xform:${u.path}`, phase: 'Transform', model: 'sonnet', isolation: 'worktree' }),
  (res, u) => agent(`Verify <transform> on ${u.path} against the spec. Refute if incomplete.`,
    { label: `verify:${u.path}`, phase: 'Verify', model: 'sonnet', schema: VERDICT }))
```

`isolation: 'worktree'` is **expensive** (~200–500ms + disk per agent) — use it only for parallel
mutation, never for read-only work. Merge branches in **dependency order** into a staging branch, run the
**full** test suite there once, then fast-forward — per-unit green checks don't prove a conflict-free
merge. (The orchestrator's job after fan-out is *integration*, not more delegation.)

The spine now offers this isolation directly — pass `isolate: true` in its `args` and every implementer
runs in a worktree, with the orchestrator inheriting the merge exactly as above. Reach for this custom
variant only when the task's **shape** differs (a Discover→Transform sweep over an unknown work-list), not
merely to get isolation.

## Pattern: judge panel (wide solution space → generate N, score, synthesize)

For design/architecture calls, generate independent attempts from different angles, score with parallel
judges, synthesize from the winner while grafting the best of the rest. Beats one-attempt-iterated.

```js
const attempts = await parallel(ANGLES.map(a => () =>
  agent(`Design <X> optimizing for ${a}. Return the approach + tradeoffs.`, { model: 'opus', schema: DESIGN })))
const scored = await parallel(attempts.filter(Boolean).map(d => () =>
  agent(`Score this design on correctness, simplicity, blast-radius. ${JSON.stringify(d)}`, { schema: SCORE })))
```

## Pattern: loop-until-dry audit (unknown-size discovery)

For "find all the X" where you don't know how many exist, keep spawning finders until K consecutive rounds
surface nothing new — a simple `while (count < N)` misses the tail. Dedup against everything *seen*, not
just what's confirmed, or judge-rejected findings reappear forever.

## Verification: keep the critic independent

Give the verifier **only the requirements + the artifact — never the implementer's reasoning trace**
(sharing it makes the critic grade the output against the frame it already built, not the requirement).
Prefer a **fresh context** (and, ideally, a different angle per critic — shuffle file order, assign
distinct lenses) over asking one agent twice. Reserve heavy skeptic panels for tasks with an objective
pass/fail surface (tests, spec conformance); they add little to open-ended judgment calls. Cap
generator↔verifier iteration (the spine is single-pass-then-escalate) — no infinite refinement, no silent
timeout-approval.

Sources: Anthropic multi-agent research system; Claude Code sub-agents & best-practices docs; git-worktree
parallel-agent guides; adversarial-review & verifier-pattern literature (2024–2026).

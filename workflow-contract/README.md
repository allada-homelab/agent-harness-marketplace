> **The executable corpus lives in the maintainer's harness layer** (private),
> beside the `run_workflow` bridges, exactly as the hook and agent corpora do.
> This file is the author-facing contract: what a module's
> `workflows/*.workflow.js` may contain and how each construct maps onto pi and
> dsh. `bin/lint-workflows.py` (run by `bin/check.sh`) is what a module's
> workflow files are validated against.

# The workflow contract

A module ships a dynamic workflow as **`workflows/<name>.workflow.js`** (or
`<name>.js`) in Claude Code's shape. Claude runs it natively with its Workflow
tool; on pi and dsh a generic bridge, installed as harness foundation, runs the
same file and exposes it through one `run_workflow` tool. A skill therefore names
a workflow once and it resolves on all three harnesses.

A workflow is the shape to reach for when the fan-out itself is the product —
a fixed graph of child agents with phases, concurrency and a checked result —
rather than a prompt that asks the model to delegate and hope.

## Manifest

```js
export const meta = {
  name: 'get-shit-done',
  description: 'Decompose a task, research it, implement each subtask …',
  phases: [{ title: 'Research' }, { title: 'Plan' }, { title: 'Implement' }],
}

const [research, plan] = await parallel([
  () => agent('Gather the external knowledge …', { label: 'research', phase: 'Research', model: 'sonnet', schema: RESEARCH }),
  () => agent('Decompose this task …', { label: 'plan', phase: 'Plan', model: 'opus' }),
])
return { research, subtasks: plan.subtasks }
```

| Field | Rule |
|---|---|
| filename | `<name>.workflow.js` or `<name>.js`, kebab-case. **The filename minus the extension is the identity**: off Claude the workflow is dispatched as `<module>:<name>`. `meta.name` is a display name and need not match it. |
| `meta` | Required, and a **pure object literal** — no identifier references, calls, template strings, concatenation or spreads. The bridges build their catalog by reading the file, not by running it; anything needing evaluation is a contract break and fails the lint. |
| `meta.name` | Required, kebab-case. |
| `meta.description` | Required. It is what the dispatcher shows the model, so write it to select the workflow. |
| `meta.phases` | Optional `[{ title }]`, in order. Progress reporting only. |
| body | Top-level `await` is available; the module body **returns JSON** — the value a caller receives. Keep it small and structured; it is read by a model. |

## Host surface

| Construct | Meaning |
|---|---|
| `agent(prompt, opts?)` | Dispatch one child. Returns its result (parsed against `schema` when given), or `null` when the child failed. |
| `parallel(thunks)` | Run zero-argument thunks concurrently; a **barrier** — resolves to an array in order, with `null` for any thunk that threw. |
| `pipeline(items, ...stages)` | Per item, run the stages in order with **no barrier between stages**: item 2 enters stage 1 while item 1 is already in stage 2. Each stage receives the previous stage's value plus the original item. |
| `phase(title)` | Declare the current phase for progress reporting. |
| `log(msg)` | One line of progress to the caller. |
| `args` | The caller's arguments object, verbatim. |
| `return <json>` | The workflow's result. |

`agent` options: `label` (progress line), `phase`, `schema` (a JSON Schema the
child's result must satisfy), `agentType` (an agent-contract type, `<module>:<agent>`
— see [`agent-contract/README.md`](../agent-contract/README.md)) and `model`
(alias: `sonnet`, `opus`, `haiku`, `inherit`). Anything else is off-contract and
the lint warns.

## Per-harness mapping

| Concern | Claude | pi | dsh | Fidelity |
|---|---|---|---|---|
| Dispatch | `Workflow({ scriptPath, args })` | `run_workflow` with `workflow: "<module>:<name>"`, `args` | same | full |
| `agent` | Agent tool child | isolated child `pi` process | `ctx.subagents` child session | full |
| `agentType` | `<module>:<agent>` subagent | the same type through the agent bridge | the same type through the agent bridge | full |
| `schema` | native | JSON-only instruction + validation of the reply | native `outputSchema` | pi re-asks, never silently coerces |
| `model` | alias | alias map or inherit | alias map, gated by the session allowlist, or inherit | inherit unless mapped |
| `parallel` / `pipeline` | harness scheduler | bridge scheduler | bridge scheduler | full |
| `effort`, `isolation`, `background`, `resumeFromRunId` | native | **ignored** | **ignored** | **degraded** |
| A child that fails | `null` | `null` | `null` | full |
| Caps | harness | 24 agents per run, 4 concurrent, 10 min per child | same | bridge-imposed |

A failed child is `null`, never a thrown exception: a workflow that does not
check for `null` silently treats a dead agent as an empty result. Guard every
result you read.

The caps are the bridges'. A workflow that needs more than 24 children or more
than ten minutes in one child is the wrong shape for this seam — decompose it
into a workflow per unit of work and let the caller drive.

Host globals outside the table above (Claude's `budget`, for instance) are
**Claude-only**; a portable workflow must not depend on one being defined.

## Writing a skill that runs a workflow

Name the workflow once and tell the model which tool runs it per harness: the
Workflow tool with `${CLAUDE_PLUGIN_ROOT}/workflows/<name>.workflow.js` on Claude,
`run_workflow` with `<module>:<name>` on pi and dsh, and a plain sequential
fallback when neither exists. A skill that hard-requires the Workflow tool is
Claude-only and must be scoped `harness: [claude]` — see
`modules/get-shit-done-claude/skills/run/SKILL.md` for the reference phrasing.

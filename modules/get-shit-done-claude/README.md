# get-shit-done-claude

The Claude Code face of get-shit-done. `/get-shit-done-claude:run <task>` turns a big task into an
orchestrated fan-out: an **Opus/Fable orchestrator** decomposes it, delegates each subtask to the
**cheapest capable model** (Sonnet for well-scoped work, Opus for hard reasoning), runs **concurrent
Sonnet research** (web + context7), fans out through a **checked dynamic workflow**, and runs an
**always-on adversarial verify** pass — two Opus critics on distinct lenses (completeness /
regressions), seeing only the requirements and the changed-file list, each returning a three-state
verdict — before reporting done. Autonomous once invoked — no per-step approval; it stops only on a
genuine blocker.

This module is claude-only (it drives the flow with Claude Code's `Workflow` tool). The portable
method skill — the loop, when-not-to-fan-out, triage rubric, verification gate — lives in the
`get-shit-done` module; install both, since this module's `/get-shit-done-claude:run` command reads
that skill for the method.

## Requirements

- **Requires the `Workflow` orchestration tool** (multi-agent fan-out). Invoking
  `/get-shit-done-claude:run` is itself the opt-in; if the tool isn't available in your session, the
  command says so and stops rather than silently no-op'ing.
- Runs best with **Opus** (or **Fable**) as your session model — the orchestrator inherits your session
  model; only subagents tier down. GSD warns if you're on a smaller model.
- Optional external reviewer/research agents (`pr-review-toolkit:*`, `task-researcher`, …) enrich the
  verify/research phases when installed, but aren't required — GSD falls back to the default worker.

## Usage

```
/get-shit-done-claude:run implement rate limiting on the public API, with tests
/get-shit-done-claude:run migrate all call sites from old_client() to new_client()
/get-shit-done-claude:run --dry-run <task>     # print the decomposition + tiers + run economics, don't spawn
/get-shit-done-claude:run --isolate <task>     # run each implementer in its own git worktree (overlapping-file tasks)
```

## What you'll see

- **Live progress** in the host's `/workflows` view — each research/implement/verify agent as it runs (and
  where the `runId` lives if you need to resume after a session loss).
- **A per-unit final report:** for each subtask, its verdict provenance — two independent Opus critics on
  distinct lenses (completeness / regressions), each seeing only the requirements and the changed-file
  list. That two-live-positive-verdicts bar is what "confirmed" means; anything less is flagged with the
  evidence. If any units ran sequentially (declared file overlap), the report discloses it.
- **Run economics:** a run spins up **~1 + 3×N agents** (one research pass + one implementer and two Opus
  verifiers per subtask) and costs **~15× a chat**. Cap it with a budget directive in your message (e.g.
  `+500k`) — the spine stops before fan-out if under ~30k tokens remain. `--dry-run` prints the estimate
  first.

## What ships

| Path | What |
|---|---|
| `skills/run/SKILL.md` | The `/get-shit-done-claude:run` entry — plans, triages, and drives the spine. |
| `workflows/gsd.workflow.js` | The spine (static-checked + smoke-tested): research ∥ plan → tiered implement (returns a changed-file list) → two-lens Opus adversarial verify (three-state verdicts). |
| `hooks/auto-trigger.example.json` + `scripts/gsd_autotrigger.py` | Optional, **disabled** auto-trigger nudge. |
| `scripts/checks.sh` | Static conformance gate (`bash …/checks.sh` → `PASS`). |

## Auto-trigger (optional, off by default)

GSD is explicit-only out of the box. To have it nudge you toward `/get-shit-done-claude:run` when a
prompt looks like fan-out work, copy `hooks/auto-trigger.example.json` to `hooks/hooks.json` (drop the
`_comment` key — `hooks.json` is strict JSON) and run `/reload-plugins`. It only ever *suggests*; it
never blocks or edits.

## Install

- Claude Code: `/plugin marketplace add allada-homelab/agent-harness-marketplace` then
  `/plugin install get-shit-done-claude@agent-harness-marketplace`

This module is Claude-only.

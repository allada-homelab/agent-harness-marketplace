# Spike: one-shot dsh subagent dispatched from a plugin

**Question.** Can a cordis plugin run background agent work after a turn ends on dsh, and what does the parent turn pay for it?

**Status.** Ran live. Scratch `DSH_HOME` (copy of `~/.dsh/profiles` + `settings.yaml` + `.credentials.yaml`, chmod 600), profile `headless`, provider `litellm`, model `fast-default`. Code: `spikes/dsh-subagent/`. Raw logs were written to the session scratchpad (`out/dsh-<mode>/spike.jsonl`), quoted below.

---

## The API that works

`ctx.subagents` is the capability seam — `@deepseek-ai/dsh-subagent/lib/types/index.d.ts:61` (`interface Context { subagents: SubagentRuntime }`), registered as `super(ctx, "subagents")` in `lib/index.js:2393`. A plugin declares `export const inject = ["subagents"]` (precedent: `@deepseek-ai/dsh-subagent-spawn-in-process/lib/index.js:12`).

One-shot dispatch is `start(name, request): Promise<SubagentRun>` — `dsh-subagent/lib/types/index.d.ts:270`. The request (`lib/types/types.d.ts:91-140`) is:

| field | required | note |
|---|---|---|
| `prompt: ContentBlock[]` | yes | the child's user message — this is the task |
| `parent: Agent` | yes | cwd, workspace, lineage, preset and model route all derive from it |
| `signal: AbortSignal` | yes | cancels before *and* after publication |
| `label?`, `maxDepth?`, `toolFilter?`, `persona?`, `agentOptions?`, `outputSchema?` | no | `persona` is the only system-prompt override; there is **no** `cwd` or `systemPrompt` field |

`SubagentRun` (`types.d.ts:240-266`): `id`, `localAgent`, `result: Promise<SubagentResult>`, `dispose()`. `result` does not reject on child failure — it resolves with `stopReason: 'completed' | 'aborted' | 'error' | 'max-tokens' | 'refusal'`. `dispose()` is mandatory.

**One-shot vs continuable** is which method you call, not a flag. `start()` yields a disposable run with exactly one result; `startContinuable()` (`index.d.ts:120`) yields a durable child with an inbox that *never* becomes a `SubagentRun` (`index.d.ts:19-23`), driven by `followup` / `interrupt` / `reportFrom`.

**No `dsh-tool-subagent` row is needed.** That package is only the model-facing tool. Programmatic dispatch needs `@deepseek-ai/dsh-subagent` (the service) plus one registered provider. Both, plus `spawn` and `fork`, are already in `dsh-base` — confirmed live on the scratch profile:

```
$ dsh --profile headless --dump-config | grep -A1 subagent
- id: subagent                     name: '@deepseek-ai/dsh-subagent'
- id: subagent-spawn-in-process    name: '@deepseek-ai/dsh-subagent-spawn-in-process'
- id: subagent-fork-in-process     name: '@deepseek-ai/dsh-subagent-fork-in-process'
```

**Same process.** Both shipped providers call `startInProcessRun`, which does `parent.ctx.agents.create(...)` on the parent's own cordis context (`@deepseek-ai/dsh-subagent-in-process-driver/lib/index.js:179`). `spawn` gives the child its own session and system prompt with `inheritsParentContext = false` (`dsh-subagent-spawn-in-process/lib/index.js:28`); `fork` seeds it with the parent's completed-turn prefix.

**Depth.** `maxDepth` is optional with **no service-level default** (the `3` is only the tool's config default, `dsh-tool-subagent/lib/index.js:37`). Exceeding it throws `SubagentDepthError: subagent depth N exceeds maxDepth M` (`dsh-subagent/lib/types/child-agent.js:32-41`).

### The seam: `agent/turn-stopping`, not `turn/end`

`'agent/turn-stopping'(payload: { agent, turn, signal })` is declared `@mode serial` at `@deepseek-ai/dsh-agent/lib/types/runtime-types.d.ts:299-305` and emitted as:

```js
// @deepseek-ai/dsh-agent-loop/lib/index.js:565
await this.dispatch.serial("agent/turn-stopping", { turn, signal });
```

`serial` awaits each listener in order (`@deepseek-ai/cordis/lib/index.js:289-295`), so **the turn boundary does not commit until every listener resolves**.

**`turn/end` is not usable.** It is not a cordis event at all — it is a session-log append (`dsh-agent-loop/lib/index.js:592`) folded by the session reducer (`dsh-agent/lib/index.js:238`). `ctx.on('turn/end')` never fires. Observing it requires the `session/event` seam instead.

---

## What was measured

Four modes, same prompt (`"hi"`), same profile, back to back:

| mode | parent wall | listener returns after | child outcome | `done.txt` written |
|---|---|---|---|---|
| `off` (control) | **1192 ms** | 0 ms | — | no |
| `detached` | **1237 ms** | **2 ms** | `aborted` at +70 ms | **no** |
| `awaited` | **6038 ms** | 4832 ms | `completed`, output `DONE` | **yes** |
| `throw` | 1225 ms, **exit 1** | — | — | no |

### Blocking is real, and so is the alternative

`awaited` cost the parent turn **+4.85 s over the control** (6038 vs 1192 ms) — the child's entire turn runs inside the parent's stop boundary, and the user watches it.

`detached` returns the listener in **2 ms** — the turn is genuinely not blocked:

```json
{"phase":"turn-stopping-enter","turn":1,"mode":"detached","depth":0}
{"phase":"turn-stopping-exit","turn":1,"mode":"detached","elapsedMs":2}
{"phase":"child-published","turn":1,"childSession":"5ffae7aa-…","local":true}
{"phase":"child-settled","stopReason":"aborted","output":"","elapsedMs":70}
```

**But the child is then killed.** In headless the host tears down as soon as the turn commits, so 68 ms later the run settles `aborted` with empty output and `done.txt` was never written. Non-blocking dispatch and surviving dispatch are not the same thing here: the child is in-process, so it dies with the process.

### Cost and inherited context

From the `awaited` run, summed over the child's own `assistant/message` events (usage is **not** on `SubagentResult`; it lives on the child's session log, `@deepseek-ai/dsh-session/lib/types/types.d.ts:279`, and must be read from `run.localAgent.session.events` *before* `dispose()`):

```json
{"messages":3,"inputTokens":3600,"outputTokens":192,"cacheReadTokens":20800}
```

A trivial "write DONE to a file" task costs ~3.8k billed tokens plus 20.8k cache reads across 3 assistant messages. The 20.8k cache read is the inherited system prompt: the child joined the parent's preset, so it got the full prompt and tool registry — it used bash to create `done.txt` in the parent's cwd, unprompted about paths. Per `child-agent.d.ts:78-110`, a child that joins no preset instead "sees an empty tool registry and none of its parent's prompt sections". Model route, cwd, workspace and sandbox override come from `parent`; approval policy is pinned to `never`.

### The recursion guard is mandatory

The `awaited` log contains:

```json
{"phase":"recursion-guard-hit","turn":1,"depth":1}
```

The child's own turn-stopping re-enters the **same** listener, because the root plugin context has no scope filter. Without `delegationDepthOf(agent) > 0 → return` (`dsh-subagent/lib/types/depth.js:18`) this recurses until the depth cap or forever. This fired on every successful run.

### Throwing fails the user's turn

`serial` has no try/catch (`cordis/lib/index.js:289-295`), so the throw propagates into the loop's turn catch (`dsh-agent-loop/lib/index.js:572-587`). Observed: the assistant's answer still printed, then

```
dsh: UNKNOWN: spike: deliberate throw inside agent/turn-stopping     (exit code 1)
```

A background-capture plugin that throws turns a successful turn into a failed one.

---

## What failed / did not run

- **Not measured: whether the child survives in a long-lived (TUI/web) host.** Only `headless` was exercised. The `aborted` result is a property of headless teardown; in a resident host the same detached dispatch plausibly completes, but that is **inferred, not measured** — confirming it needs a run under `--profile web` or an RPC-style host.
- **Upstream flakiness cost several runs.** `model: large-default` returned `EMPTY_RESPONSE: model "large-default" returned a completed response with no content` on every attempt for ~10 minutes, including the unpatched control, so it was not caused by the spike. Switching the scratch `settings.yaml` to `fast-default` (and deleting `reasoningEffort`, which that model rejects with `UNSUPPORTED_REASONING_EFFORT`) fixed it. The prompt text also mattered: `"reply with exactly: PARENT_OK"` reliably produced `EMPTY_RESPONSE` while `"hi"` did not.
- **pnpm `file:` installs are copies, not links.** `dsh plugin add file:<dir>` hard-copies the package; editing the source afterwards has no effect and `pnpm install --force` did not re-copy. Iterating required copying `lib/index.js` over the installed path.
- **`--patch` config overrides work; env vars do not reach the plugin.** `SPIKE_MODE` set in the parent shell never arrived (dsh sanitizes the app environment). Per-run config must go through a `--patch` overlay: an id-targeted entry (`- id: spike-dsh-subagent` / `config: {...}`) is merged over the bundle's own row. Note the **user `settings.yaml` layer outranks a `--patch` overlay** — overriding `agent-default-model` needed a settings edit, not a patch.
- `ctx.subagents.list()` is `[]` at plugin-apply time; providers register later. Resolve the provider at dispatch time, not at apply.

## Consequences for okf-wiki design

1. **There is no free post-turn seam on dsh.** `agent/turn-stopping` is the only one, and it is serial and awaited. Any capture work done there is on the user's critical path: measured **+4.85 s** for a trivial child.
2. **Non-blocking means "not completed" in headless.** A fire-and-forget in-process child is aborted at host teardown (70 ms) with no output and no side effects. On dsh, the choice for a headless one-shot is *block and get a result* or *dispatch and get nothing* — there is no third option in-process. Durable post-turn work needs an out-of-process transport (the `acp` provider referenced at `dsh-subagent/lib/types/index.d.ts:13` is not installed here) or a resident host.
3. **Isolation is good and cheap to control.** `spawn` gives an independent session with zero parent conversation, and `toolFilter` / `persona` / `agentOptions` narrow tools, prompt and model per child. Use them: the default is full preset inheritance.
4. **Budget ~4k tokens + ~20k cache read per capture child**, minimum, before the task itself does anything.
5. **Two non-negotiables in the handler**: a `delegationDepthOf(agent) > 0` early return (measured re-entrancy), and a total try/catch (a throw fails the user's turn with exit 1).
6. **Read usage before `dispose()`** — it is on the child's session events, not the result.

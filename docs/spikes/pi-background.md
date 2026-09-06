# Spike: detached background `pi -p` from `agent_settled`

**Question.** Can a pi extension run background agent work after a turn ends, and how does the result get back in front of the model?

**Status.** Ran live, end to end, including the injection actually being read by the model on the next turn. Scratch `$HOME` with copied `auth.json` / `models.json` / `settings.json` / `trust.json` (chmod 600), provider `llama-swap`, model `large-default:agent` (`deepseek-ai/DeepSeek-V4-Flash-Vision-Exp`). Code: `spikes/pi-background/`. `PKG` below = `~/.nvm/versions/node/v24.15.0/lib/node_modules/@earendil-works/pi-coding-agent`.

---

## The API that works

**Seam.** `agent_settled` carries an empty payload — `interface AgentSettledEvent { type: "agent_settled" }` (`PKG/dist/core/extensions/types.d.ts:545`). The chain is **serial and awaited**: `for (const ext …) for (const handler …) await handler(event, ctx)` (`PKG/dist/core/extensions/runner.js:579`), emitted as `await this._extensionRunner.emit({type:"agent_settled"})` before the idle wait resolves (`PKG/dist/core/agent-session.js:327`). An async handler that awaits the child *would* block settle. Handler errors are caught per-extension and are not fatal (`runner.js:594-605`).

**`pi.exec` cannot detach.** `exec(command, args, options?): Promise<ExecResult>` (`types.d.ts:944`) with `ExecOptions = { signal?, timeout?, cwd? }` (`PKG/dist/core/exec.d.ts:7`) — no `detached`, no `stdio`, no `env`, and the whole process is buffered and awaited. Used `node:child_process.spawn` instead, matching the shipped example (`PKG/examples/extensions/subagent/index.ts:335`), with its `getPiInvocation` helper (`:248-262`) to locate pi itself.

**Two injection channels, and they are not equivalent:**

- `pi.appendEntry(customType, data)` (`types.d.ts:936`) writes a `custom` session entry that explicitly **does not participate in LLM context** (`PKG/docs/extensions.md:1440`, `session-format.md:340`). State only.
- `pi.sendMessage({customType, content, display}, {deliverAs})` (`types.d.ts:924`) writes a `custom_message`, which **is** in context (`session-format.md:339`). `deliverAs: 'nextTurn'` queues it for the next user prompt without interrupting or triggering a turn (`extensions.md:1407`); `'steer'` and `'followUp'` deliver into the current turn.

---

## What was measured

### The parent does not block

```json
{"phase":"agent-settled-enter","cwd":"…/work"}
{"phase":"child-spawned","pid":2901127,"args":["-p","--no-session","-ne","-ns","-nc","-na","Write the single word DONE…"]}
{"phase":"agent-settled-exit","elapsedMs":4}
{"phase":"child-closed","code":0,"elapsedMs":1982,"out":"DONE"}
```

**Handler returns in 4-5 ms** across every run. The child took **1982 ms** wall and wrote `child-done.txt` in the parent's cwd.

### The model really does see it on the next turn

Measured with a two-turn RPC session (`pi --mode rpc`), because `pi -p` exits before the child finishes (see below). On turn 2, the injected message arrives ahead of the assistant's reply:

```json
{"type":"message_end","message":{"role":"custom","customType":"spike-bg-result",
 "content":"[spike] background pi child exited 0 in 1982ms:\nDONE","display":true}}
```

and the model quotes it back verbatim:

> The background notice I received is: ```[spike] background pi child exited 0 in 1982ms: DONE```

`appendEntry` produced no model-visible message, exactly as documented. **`sendMessage(..., {deliverAs:'nextTurn'})` is the channel that works; `appendEntry` is for extension state only.**

Parent turn cost, before/after injection: turn 1 `input 155, output 6, cacheRead 1536` (total 1697); turn 2 `input 203, output 30` (total 1769). The notice cost **+48 input tokens** in the parent's context.

### `pi -p` kills the injection path — with a specific error

In headless `-p`, `session_shutdown` fires **in the same millisecond** as `agent-settled-exit`, ~2 s before the child finishes. The captured `pi` handle is then stale, and the injection throws an uncaught error that **crashes the parent after it printed its answer**:

```
Error: This extension ctx is stale after session replacement or reload. …
    at Object.appendEntry (…/dist/core/extensions/loader.js:272)
```

So in `-p` the result has nowhere to go. Two viable shapes: keep the session alive (RPC/TUI), or write the child's output to a file and pick it up on the next `session_start`.

### Fire-and-forget does survive parent exit

With `stdio: "ignore"` + `child.unref()`, the parent exits at 5 ms and the child **still completed and wrote `child-done.txt`** after the parent was gone. That is the durable-background option — at the cost that the result can never come back through that process.

### Child cost and inheritance

Two children, same task, same scratch `$HOME`:

| child | wall | LLM calls | tokens (in / out / cacheRead) |
|---|---|---|---|
| lean (`-ne -ns -nc -na`) | 2.05 s | 2 | 172+286 / 101+4 / 1536×2 |
| full discovery | 2.00 s | 2 | 172+295 / 101+4 / 1536×2 |

~3.6k total tokens for a trivial task. **Caveat: this comparison under-measures inheritance.** The scratch `$HOME` has no extensions, skills or `AGENTS.md`, so the two runs are near-identical by construction. Against a real `~/.pi` the discovery flags are what stop the child loading the parent's whole extension and skill set — that delta was **not measured**.

### Recursion guard and session hygiene

- The env guard fires: with `SPIKE_PI_CHILD=1` the extension logs `child-guard-hit` and registers nothing, even when loaded with an explicit `-e`. `-ne` alone covers discovery-loaded copies; the env var is what covers an explicit `-e`.
- `--no-session` keeps children out of the sessions tree entirely: after all runs, `find $HOME/.pi/agent/sessions -name '*.jsonl' | wc -l` was still **1** — the original baseline session, no child files.
- Session JSONL lives at `$HOME/.pi/agent/sessions/<cwd-slug>/<ISO>_<uuid>.jsonl`; per-assistant usage is `{input, output, cacheRead, cacheWrite, reasoning, totalTokens, cost{…}}` (`PKG/docs/session-format.md:104-117`). `--session-dir <dir>` redirects it, which is how the child costs above were captured.

---

## What failed / did not run

- **Injection in `pi -p` is impossible**, per the stale-ctx crash above — the only genuine failure found.
- **Real-`$HOME` inheritance cost not measured** (see caveat), deliberately: the brief forbade running against the real `~/.pi`.
- **`before_agent_start` not exercised.** Everything was done from `agent_settled`, per the known deadlock when an async yield happens inside `session_start`.
- The child's own stdout is the only result channel used; `--mode json` on the child (which the shipped example uses) would give structured usage without a session file, and was not tried.

## Consequences for okf-wiki design

1. **pi has a clean non-blocking post-turn seam.** `agent_settled` + `spawn(detached)` returns in **4 ms** and does not touch the turn's critical path. This is materially better than dsh, where the only seam is serial and awaited.
2. **Isolation is per-flag and cheap.** `-ne -ns -nc -na --no-session` gives a child that inherits no extensions, skills, context files, project trust, or session file — the recursion risk and the inherited-cost risk are the same switch.
3. **Two guards, both needed.** `-ne` stops discovery-loaded recursion; an env marker (`SPIKE_PI_CHILD`) stops explicit-`-e` recursion. Both verified.
4. **Delivery must match host lifetime.** In a resident session (TUI/RPC), `sendMessage(..., {deliverAs:'nextTurn'})` is model-visible and costs ~50 tokens. In `pi -p` the session is gone before the child finishes, and calling the API there **crashes the process** — so a headless capture must be fire-and-forget with a file drop, replayed on the next `session_start`.
5. **Never `appendEntry` and assume the model sees it.** It is invisible to the LLM by design; it is the right place for the child's pid/status, and the wrong place for its findings.
6. **Budget ~3.6k tokens and ~2 s per capture child**, plus ~50 tokens in the parent when the result is injected.

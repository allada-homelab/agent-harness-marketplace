# dsh Plugin Capability Knowledge Base

> A maintainer reference for what the installed DeepSeek Harness (`dsh`) can do today,
> plugin by plugin, with the subagent/delegation capabilities called out separately
> because they changed recently and the skills/docs in this repo do not all reflect them.

**Scope.** Every cordis plugin shipped with `@deepseek-ai/dsh` `0.1.5-rc.2` as installed in this
session's harness: **230 `@deepseek-ai/dsh-*` plugins** plus the **10 foundation packages**
(`cordis`, `cordis-plugin-*`, `cosmokit`, `schemastery`, `node-addon-system*`). The `dsh-*`
plugins are the real capability surface; the foundation packages are the runtime they ride on.

**How it was built.** Each plugin's `README.md` (the package-reference doc shipped with every
package) was read and condensed to: what it does, its notable capabilities, its documented
config fields + defaults, whether it participates in the subagent/delegation story, and any
limitations. Claims are grounded in those READMEs (one package, `dsh-web-frontend`, has no
README, so its entry comes from `package.json`). Nothing here is inferred from memory — every
entry traces to the shipped doc for that package.

**Plugin names** are `@deepseek-ai/<name>`; they are referred to below by `<name>` only, to
keep the file readable and free of absolute paths.

> **⚠️ As of — and it may change.** This knowledge base is a **point-in-time snapshot**: the
> capabilities below are exactly what the installed dsh (`0.1.5-rc.2`) shipped on the day it was
> written. dsh evolves quickly — new plugins land, existing ones grow capabilities and change
> defaults. **Do not treat an entry here as current spec**; before relying on any capability,
> config field, or default, re-verify it against the dsh version actually installed in the session
> or environment you are working in.

---

## 1. Capability map at a glance

| Domain | Plugins | What it is |
|---|---|---|
| Core agent & boot | 16 | The Agent handle, the agent loop, model defaults, AGENTS.md instructions, per-session presets, tool presentation, base bundle, boot, persona, system prompt, scope, invariants |
| **Subagents & workflow** | **13** | **The delegation seam, the model-facing subagent tools, spawn/fork backends, continuable children, control tools, workflow engine, Ralph loop, background jobs** |
| Model-facing tools | 18 | The tool registry + every tool the model can call (bash, fs, web, skill, todo, jobs, goal, present, ask-user, cordis, ralph, workflow…) |
| Sessions & persistence | 24 | Event-sourced session store, durability checkpoints, format migration, JSONL persistence, projections, query (SQLite FTS5), references, stats, titles, telemetry, export, feedback |
| Goals, schedule, compaction | 14 | Persisted same-session goals, round driver, `/goal`, schedule, `/compact`, compaction policy + summarizer, tool-result pruner, time/tmux context, token meter, timeout, output retention |
| FS, shell, sandbox, subprocess | 24 | `ctx.fs`, `ctx.shell`, `ctx.sandbox`, `ctx.subprocess`, terminals, spill, code-runtime, Win32 primitives — abstract seams + local/sandboxed backends |
| LLM, web, hooks, MCP | 18 | Provider-neutral LLM service, DeepSeek + pi-ai adapters, retry, web search/fetch, webhook runtime, Claude Code / Codex hook bridges, MCP client bridge |
| Storage, settings, credentials | 22 | Storage hub + domain + JSON, settings, credentials, workspace registry, attachments, file references, atomic write, util libraries |
| SDK, ACP, API, cordis runtime | 17 | ACP automation server, SDK profiles + JSON-RPC, client/host API controllers, cordis host/client runners, Typert protocol |
| Human-facing seams & skills | 10 | Approval, user questions, permission presets, plan mode, commands, native command, authorization, skill providers |
| Client host & plumbing | 14 | Browser wire, file upload, HMR, locale, client module system, resources, directory pickers, SPA dist, open-in-app, plugin inventory, webserver |
| Client UI (A) | 24 | Chat, conversation, layout, settings, sidebar, reference, renderer, model selection, plan, goals, jobs, schedule, feedback… |
| Client UI (B) | 16 | Settings sections, plugins, sidebar files/docs, skill, theme, tool tree, trajectory, workflow-run, workspace, user-questions… |
| Foundation | 10 | cordis meta-framework + loader/include/group/hmr/timer, cosmokit, schemastery, Landlock/flock addons |

**Subagent-relevant plugins** (the ones that actually shape delegation): `dsh-subagent`,
`dsh-tool-subagent`, `dsh-tool-subagent-control`, `dsh-subagent-fork-in-process`,
`dsh-subagent-spawn-in-process`, `dsh-subagent-in-process-driver`, `dsh-client-ui-subagent`,
`dsh-tool-ralph`, `dsh-workflow`, `dsh-tool-workflow`, `dsh-workflow-worker-thread`,
`dsh-tool-jobs`/`dsh-jobs-local` (background jobs), `dsh-goal`, `dsh-tool-goal`,
`dsh-agent`, `dsh-agent-loop`, `dsh-agent-presets`, `dsh-scope`, `dsh-base`,
plus `dsh-user-approval` / `dsh-user-questions` / `dsh-plan-mode` / `dsh-skill` (delegation
authority + refusal behavior) and `dsh-session-*` (durable child state, projections, query).

---

## 2. The subagent & delegation stack (the recent change)

This is the area the older skills/docs lag. dsh now ships a full delegation subsystem: the
**seam** (`ctx.subagents`), **provider backends**, **model-facing tools**, **control tools**,
and a **workflow / Ralph** layer on top. Below is the current shape.

### 2.1 The model-facing delegation tools (shipped `standard` preset)

The default preset mounts one named tool per delegation target. All of these are what an agent
actually sees:

| Tool | Provider | Mode | Purpose |
|---|---|---|---|
| `subagent` | `spawn` | **continuable** | Fresh child, empty conversation; inherits cwd/lineage/model unless overridden |
| `subagent_fork` | `fork` | **continuable** | Child seeded with the parent's completed turns (not the in-flight one) |
| `subagent_codex` | `codex` | one-shot | Child on an out-of-process Codex backend |
| `subagent_claude_code` | `claude-code` | one-shot | Child on an out-of-process Claude Code backend |
| `send_message` | — | — | Follow-up / steer a direct continuable child (or resident child → its live parent) |
| `interrupt_agent` | — | — | Stop a child's current turn; keep its inbox and descendants |
| `list_agents` | — | — | List direct children / the whole descendant tree |
| `list_subagent_models` | — | — | Advertised child provider/model/effort catalog (only with model selection enabled) |
| `workflow` | `spawn` | foreground | Run a JS orchestration script that fans out to subagents |
| `ralph` | `spawn` | foreground | Fresh-agent loop toward one immutable objective |
| `job_output` / `job_list` / `job_kill` | — | — | Collect / list / stop a background job (one-shot background mode) |

`modelSelectionSettings: true` on the `subagent` tool exposes `provider`, `model`, and
`reasoning_effort` call fields plus `list_subagent_models`. The `subagent_fork` row deliberately
omits model selection so provider/model stay equal to the parent and the inherited history stays
eligible for KV-cache reuse.

### 2.2 The seam: `ctx.subagents`

`@deepseek-ai/dsh-subagent` is a named-provider registry. Mounting the service alone changes
nothing — you also need at least one provider backend and a delegation tool.

- **One-shot vs continuable is which method you call**, not a flag.
  `start(provider, request)` returns a disposable `SubagentRun` with exactly one result
  (`stopReason: completed | aborted | error | max-tokens | refusal`). `startContinuable(...)`
  returns a durable child with an inbox — a stable child id, in-order follow-up messages, and
  interruption — that is never a `SubagentRun`.
- **Programmatic dispatch does not need a tool row.** A plugin declares
  `export const inject = ["subagents"]` and calls the seam directly; `dsh-tool-subagent` is
  only the model-facing surface.
- A child gets a **fresh, flat registration scope** — the parent's tool restrictions and
  authority are never imported.

### 2.3 Providers

- **`spawn`** (`dsh-subagent-spawn-in-process`) — fresh child on the same process/agent factory.
  Empty conversation, so the prompt must stand alone. Cheapest transport.
- **`fork`** (`dsh-subagent-fork-in-process`) — like spawn but the child is seeded with a
  one-time snapshot of the parent's **balanced completed-turn prefix** (never the in-flight
  turn; empty before the first completed turn behaves like spawn). Keeps the child eligible for
  KV-cache reuse under the same provider/model.
- **`codex` / `claude-code`** — out-of-process children (one-shot, `maxDepth: provider-managed`).
- **`acp`** — ACP children with their own runtime; one-shot and not trace-enumerable today.
- **`sdk`** — out-of-process SDK children (via the SDK profile; `sdk-minimal` deliberately
  excludes subagents).

Both in-process backends share `dsh-subagent-in-process-driver`, which creates the child through
the host agent factory, applies per-child customization, drives one task, and returns the child's
own final output with a single quiescent disposal path.

### 2.4 Child configuration & caps

Per child (via `agentOptions`, `persona`, `toolFilter`, `maxDepth` — per call on the seam, per
tool-instance on the model-facing tool):

- **`agentOptions`** — child `provider`, `model`, adapter-owned `reasoningEffort`, positive
  `maxTokens`. Every requested option requires the provider's matching capability; an unsupported
  one fails loudly at start, never silently.
- **`persona`** — per-child persona (requires the provider's `persona` capability).
- **`toolFilter`** — per-child global-tool restriction (requires `toolFilter`).
- **`maxDepth`** — absolute delegation-depth cap; **default `3`**, `0` forbids delegation,
  `'provider-managed'` sends no cap to an out-of-process provider. The tool stays visible at the
  cap; each attempted start re-checks the calling agent's depth and rejects with an errored result.
- **`backgroundMode`** — `one-shot` (default: calls wait in the foreground) vs `continuable`
  (default: start a durable child in the background). Requires `prepareContinuable` for the latter.
- **`enableRunInBackground`** — expose `run_in_background`; disabling also rejects forced calls.

### 2.5 Continuable children: messaging, interrupt, discovery

- `sendMessage()` — only **adjacent** Agents communicate: any exact live sender may target a
  direct continuable child; only a resident continuable child may target its **direct live parent**.
  Returns acceptance (a stable `messageId`), never a reply; a failure states the message was not
  delivered.
- `interrupt_agent()` — stops only the current turn; queued messages stay parked, descendants
  keep running, and the child stays available for later messages.
- `list_agents` — direct `children` scope and `descendants` (whole tree, stable pre-order), with
  live-registry status (`running` / `idle` / `ready`). A snapshot, not a delivery promise.
- A **delegation-scope statement** is injected into every in-process child's runtime context:
  *"You are a delegated subagent: your permission scope was fixed when you were started and cannot
  be widened from inside this session — operations that require approval are rejected
  automatically."* This is why a subagent calling `ask_user_question` is refused
  (`DELEGATED_CALLER`) and must fold the unresolved question into its final result instead.
- The **browser UI** (`dsh-client-ui-subagent`) shows the subagent catalog: the descendant tree,
  running state, token use, active-turn duration, a continuation composer for live continuable
  children, and an independent Stop.

### 2.6 Model selection for children

With model selection enabled, the tool exposes `provider`/`model`/`reasoning_effort` and a global
`list_subagent_models`. A call supplies provider+model together, or only an effort when defaults
provide the route. Static `agentRouteDefaults`, tool config, and model fields overlay in order
before route-aware effort merging and exact-route preflight. The live adapter validates the
effective route before child creation; catalog membership stays advisory. The session's
`subagent-model-selection` preference (allowlist of exact provider/model routes) is enforced at
execution as well as at discovery.

### 2.7 Background subagent jobs

- **one-shot + `run_in_background: true`** starts a plain parent-owned background job and returns
  `started background subagent job <id>`; collect with `job_output`, stop with `job_kill`.
- **continuable mode** (omitted/`true`) starts a durable child and returns `started subagent
  <childId>` without waiting. One settlement notice arrives when the child's Activation ends;
  follow-up goes through `send_message`. Set `run_in_background: false` to wait in the foreground.

### 2.8 Workflow engine & the `workflow` tool

`ctx.workflowEngine` (`dsh-workflow`, implemented by `dsh-workflow-worker-thread`) runs a
plain-JavaScript orchestration script that fans work out to subagents and returns the script's
final JSON value. Scripts use `agent()`, `parallel()`, `pipeline()`, `phase()`, `log()` hooks;
`meta`/`args` arrive as plain JSON data, never evaluated code. Each run gets its own worker thread
(off the host event loop), is validated up front, has concurrency/backstop caps, and cancels
boundedly. The model-facing `workflow` tool is used only when the user explicitly asks for a
workflow or large multi-agent orchestration; the parent turn waits until every child settles.

### 2.9 Ralph loop

The `ralph` tool is a fixed foreground fresh-agent loop toward one immutable objective — used
**only when the direct human explicitly requests Ralph-style fresh-agent iteration**. Each round
opens a fresh child with only the objective, round/cap, and the previous bounded report; the
workspace is long-term memory. Terminal state is `complete`, `blocked`, or budget-limited.

### 2.10 What changed vs. what the older docs say

The short version — things a reader of the older skills/docs would get wrong today:

1. **Subagents are continuable now.** They are not one-shot-and-done. A child has a durable
   session, a stable id, and accepts follow-up turns via `send_message`, can be interrupted with
   `interrupt_agent`, and shows up in `list_agents`. The web UI can continue a running child.
2. **`fork` exists.** A child can be seeded with the parent's completed turns (without seeing the
   in-flight one), distinct from a standalone `spawn` child that gets an empty conversation.
3. **Children can run in the background** and be collected/stopped via the jobs tools, and a
   settlement notice is delivered to the parent.
4. **Per-child model selection.** The parent can pick the child's provider/model/effort through
   the tool and query the catalog via `list_subagent_models`; a session allowlist governs it.
5. **Per-child persona, tool filter, and a depth cap** (default 3, `0` forbids delegation).
6. **The delegation-scope statement** — a delegated subagent's permission scope is fixed at start
   and approval is auto-rejected, so it cannot widen its own authority.
7. **The model-facing surface is a family of tools** (`subagent`, `subagent_fork`, `subagent_codex`,
   `subagent_claude_code`, `send_message`, `interrupt_agent`, `list_agents`, `list_subagent_models`,
   `workflow`, `ralph`) — not a single `delegate_agent` tool.
8. **The subagent model allowlist** is a session-level preference, not a fixed per-tool list.

---

## 3. Model-facing tool inventory (shipped `standard` preset)

The tools an agent actually gets, by capability family (name — what it does):

- **Filesystem & search:** `read`, `write`, `edit` (over `ctx.fs`; observed-state, read-before-edit,
  version-guarded mutations), `glob`, `grep` (packaged ripgrep binary), `present` (declare
  deliverables).
- **Shell:** `bash` (with optional generic background job + sandbox escalation), `bash` persistent
  twin (`backendType`, `timeoutMs`, `maxOutputChars`), `pwsh` (+ persistent twin).
- **Web:** `web_search`, `web_fetch` (over `ctx.web`; anonymous HTTP fetch + DeepSeek search).
- **Skills:** `skill` (load a skill body into context; catalog description capped).
- **Subagents:** `subagent`, `subagent_fork`, `subagent_codex`, `subagent_claude_code`,
  `send_message`, `interrupt_agent`, `list_agents`, `list_subagent_models`, `workflow`, `ralph`.
- **Tasks & tracking:** `todo_write` (event-sourced), `create_goal`/`get_goal`/`update_goal`
  (same-session persisted goals, execution-time authority checks), `job_output`/`job_list`/`job_kill`.
- **Human:** `ask_user_question` (refused in a subagent — `DELEGATED_CALLER`).
- **Self-referential:** `cordis` toolset (inspect the live runtime, mount/dispose plugins).
- **Guards:** `tool-call-timeout-policy` (per-tool deadline), `repeat-tool-reminder` (advisory
  reminder on identical-call loops), `compaction-tool-result-pruner` (head/middle/tail pruning).

Tool presentation is per-preset (`native` / `ptc` / `both`) via `dsh-agent-tool-presentation`.

---

## 4. Domain catalog

Entries below are `@deepseek-ai/<name>` with the capability summary; key features, config
defaults, and limitations follow where the package documents them. Groups 1 and 2 (core agent,
subagents) are written out in full; groups 3–14 are the machine-extracted catalog.

### Core agent & boot — 16 plugins

**`@deepseek-ai/dsh-agent`** — The Agent handle, live registry, process-local initiator scope, and
`agent/*` event vocabulary. `create()`/`resume()` return an `AgentHandle` that is the only object
able to tear the agent down (ownership is a capability). Drive methods: `followup()`, `steer()`,
`inject()`, `cancel(cause)`, `whenIdle()`. Agent-scoped registrations (tools, prompt sections,
variables, listeners) apply to one agent and unwind on disposal. Events: pre-step, request-error,
turn-stopping, assistant-stream, status, created, disposed, inbox/*. The initiator scope is
process-local and must be carried explicitly across workers/processes/restarts; `cancel()` clears
the inbox unless `keepInbox` is set. **Subagent-relevant.**

**`@deepseek-ai/dsh-agent-loop`** — The default driver: creates fresh agents or resumes persisted
sessions, then drives each turn (model requests, streamed responses, tool execution, durable
history). Registers itself as the AgentFactory behind `ctx.agents`. Bounded parallel tool pool
(`maxParallelToolCalls` default 10; 1 = serial), cooperative cancellation, durable inbox driven by
normalized `agent/inbox/spliced` events, persistence integration via `ctx.sessionPersistence`.
Config agents: `id`, `provider`/`model`, `reasoningEffort`, `maxTokens`, `cwd`, `sessionId`,
`resumeSessionId`. No per-agent persona field or setup hook in config (programmatic only); no
built-in turn budget. **Subagent-relevant.**

**`@deepseek-ai/dsh-agent-default-model`** — Shared default provider/model for fresh agents whose
sessions don't specify one. `currentSelection()` / `saveSelection()`. `reasoningEffort` is
deliberately not a config field.

**`@deepseek-ai/dsh-agent-instructions`** — Injects AGENTS.md/CLAUDE.md guidance from user-global
(`$DSH_HOME/AGENTS.md`) then project root down to cwd as durable conversation content. Byte budget
renders most-specific first; touch-driven refresh on structured fs activity; content-based dedup;
resume reconciles. Discovery follows structured fs tools, not `bash cd`.

**`@deepseek-ai/dsh-agent-presets`** — Composes each session from one preset's `agent.cordis.yml`
(its own tools, prompt sections, skills). Roster = shipped + configured roots + user root; authoring
is copy-only; broken presets list the offending rows; a session may switch presets only while it
has produced nothing. A child agent (subagent) joins its parent's composition. **Subagent-relevant.**

**`@deepseek-ai/dsh-agent-tool-presentation`** — Per preset, which form of tools the model sees:
`native`, `ptc` (run_code + generated SDK, needs a code runtime), or `both`. One presentation per
agent; a second declaration is refused.

**`@deepseek-ai/dsh-base`** — The shared core bundle every base-backed profile (web, headless, sdk,
acp) runs on: a model connection, the full tool set, durable sessions, workspace safety defaults,
subagents, task/goal tracking. A patch entry replaces the target's whole config (no deep merge).

**`@deepseek-ai/dsh-app-boot`** — Loader boot library: layered `.env` loading, profile resolution
(web/headless/acp/sdk/sdk-minimal) with bundles and `cordis.patch.yml`, fail-loud diagnostics,
config preview, `cordis:include`/`cordis:group` builtins.

**`@deepseek-ai/dsh-cmdline`** — App bins parse their own flags from the args left after launcher
flags; `ctx.appExit`/`ctx.appReady` lifecycle; a flag beats the `!!js` fallback.

**`@deepseek-ai/dsh-launch-environment`** — Immutable snapshot of the run's env remembering which
layer (inherited process env, `<cwd>/.env`, `$DSH_HOME/.env`) supplied each value, in a fixed
trust order; `launchedThroughSsh()` detection.

**`@deepseek-ai/dsh-persona`** — Composable persona row (prefix/suffix sections) shadowing the
deployment defaults for one agent; `complete: true` makes the prefix the sole prompt section;
`includeRuntimeContext: false` suppresses runtime-context snapshots. Only usable from a scoped
composition.

**`@deepseek-ai/dsh-system-prompt`** — System-prompt assembly registry: sections, dynamic runtime
facts, variables, tool-schema sources, with agent-scoped shadowing. `complete: true` section
becomes the exact prompt; strict unknown-variable failure; `toolOrder` with one
`<unlisted-tools>` rest entry.

**`@deepseek-ai/dsh-scope`** — Scoped-registration primitive: each agent/group gets an isolated
contribution set with a shared lifetime; child scopes inherit ancestor contributions (nearest wins),
ancestors observe descendants; `dispose()` unwinds. Only scope-aware APIs isolate state. **Subagent-relevant.**

**`@deepseek-ai/dsh-invariants`** — Runs package-owned runtime invariant checks inside a
composition; a failed check reports `InvariantError` attributed to the owning package. Filters via
`package_allowlist`/`package_blocklist`.

**`@deepseek-ai/dsh-headless`** — One-shot task mode: `dsh --profile headless 'task'` runs one task
and exits (0 on completed final turn, 1 otherwise), streaming reasoning to stderr and the answer to
stdout. No server/browser.

**`@deepseek-ai/dsh-package-manifest`** — Shared TypeScript declarations for `package.json.dsh`
(bundle, profile, client, configTrees, sessionFormatMigration, moduleFallback). Types only.

### Subagents & workflow — 13 plugins

**`@deepseek-ai/dsh-subagent`** — The delegation seam: named-provider registry routing requests to
child-agent backends; one-shot and continuable children; `sendMessage()` with exact adjacent
Agents; discovery of children/descendants without loading them. Enabling it alone changes nothing.
Limitations: ACP children one-shot and non-trace-enumerable; no durable parent mailbox (a missing
parent rejects child-to-parent delivery); process-local residency. **Subagent-relevant (core).**

**`@deepseek-ai/dsh-tool-subagent`** — The model-facing delegation tool. One instance per target
with a distinct `toolName`; the tool exists exactly while its provider does. Config: `provider`
(required), `toolName` (`subagent`), `modelSelectionSettings` (`false`), `enableRunInBackground`
(`true`), `backgroundMode` (`one-shot`), `agentOptions`, `persona`, `toolFilter`, `maxDepth` (`3`).
The tool description adapts to `provider.inheritsParentContext` (fresh "does not see conversation"
vs fork "does not see in-flight turn"). **Subagent-relevant (core).**

**`@deepseek-ai/dsh-tool-subagent-control`** — The global control tools for continuable children:
`send_message` (steer, acceptance-only), `interrupt_agent` (stop current turn, keep inbox +
descendants), `list_agents` (children/descendants, stable pre-order, live-registry status). Takes no
configuration. **Subagent-relevant (core).**

**`@deepseek-ai/dsh-subagent-spawn-in-process`** — Fresh-child backend (provider `spawn`): empty
conversation, inherits parent cwd/lineage/provider/model/effort/output cap, fresh flat scope, one
child per call, final output only. **Subagent-relevant (core).**

**`@deepseek-ai/dsh-subagent-fork-in-process`** — Seed-with-parent-turns backend (provider `fork`):
one-time snapshot of the parent's balanced completed-turn prefix; never the in-flight turn; empty
seed behaves like spawn; KV-cache-eligible under the same provider/model. **Subagent-relevant (core).**

**`@deepseek-ai/dsh-subagent-in-process-driver`** — The shared run driver behind spawn/fork: creates
one child via the host agent factory, applies per-child customization, drives one task, returns the
child's own final output, quiescent disposal. Supports optional structured-output runtime; carries
the parent's sandbox override and `never` approval pin; child depth = parent depth + 1. Runs are
one-shot only (no sendMessage/resume). **Subagent-relevant (core).**

**`@deepseek-ai/dsh-client-ui-subagent`** — Web subagent catalog, continuation-routing UI, and `@`
reference source: descendant tree, running state, token use, active-turn duration, FIFO follow-up
composer for live continuable children, independent Stop. `@` references are display-title text,
deliberately inert. **Subagent-relevant.**

**`@deepseek-ai/dsh-tool-ralph`** — Fresh-agent Ralph loop. Config: `subagentProvider` (`spawn`),
`maxRounds` (`256`), `maxHandoffChars` (`16384`), `maxResultChars` (`16384`). Completion is
worker self-declaration; foreground only; provider must support structured output and
`inheritsParentContext: false`. **Subagent-relevant.**

**`@deepseek-ai/dsh-workflow`** — Workflow orchestration seam (`ctx.workflowEngine`): runs a plain-JS
script with `agent()`/`parallel()`/`pipeline()`/`phase()`/`log()`, returns the script's final JSON.
Result never rejects (script failure → `stopReason: 'error'`); caller owns and must `dispose()`.
Foreground collection only; no journaling/resume. **Subagent-relevant.**

**`@deepseek-ai/dsh-tool-workflow`** — Model-facing workflow tool. Config: `toolName` (`workflow`),
`maxResultChars` (`50000`). Parent turn blocks until the workflow settles; cancellation/failure
return errors, never partial success; `args` must be an object. **Subagent-relevant.**

**`@deepseek-ai/dsh-workflow-worker-thread`** — Worker-thread engine: one worker per run in an
escapable `node:vm`; agent() calls cross a typed protocol back to `ctx.subagents`. Config:
`provider` (`spawn`), `maxConcurrentAgents` (`0` → CPU-derived), `maxTotalAgents` (`1000`),
`maxItemsPerCall` (`4096`), `syncTimeoutMs` (`5000`), `disposeGraceMs` (`5000`). The worker/vm is
**not** a security boundary. **Subagent-relevant.**

**`@deepseek-ai/dsh-jobs`** — Background-job registry contract (`ctx.jobs`): stable `<kind>-N` ids,
owner-fenced access, output read/wait/list/cancel, completion notice. In-process contract; an
unowned job is open to any caller (authorization, not secrecy).

**`@deepseek-ai/dsh-jobs-local`** — Process-local jobs implementation. Config:
`maxConcurrentJobsPerOwner` (`10`). Preflight before start; jobs die with the harness process; a
silently ineffective cancel can stall teardown. **Subagent-relevant** (background subagent jobs).


### Model-facing tools — 18 plugins

**`@deepseek-ai/dsh-tools`** — The tool registry and execution pipeline for all model-facing tools: tool authors register typed definitions with defineTool, calls are validated against parameter schemas, allow/deny/ask policy is enforced, and finalized results are returned without ending a turn on ordinary failures. Supports native function calling, PTC mode (a reserved run_code transport plus a generated SDK), or both.
  - defineTool typed definitions with parameters, output schema, and execute body
  - Per-agent restrict() allow/deny masks that narrow the visible tool set
  - Execution pipeline: tools/pre-execute, monotonic guards, tools/execute, tools/post-execute, tools/result
  - PTC mode: generated per-language SDK and run_code dispatch bridge
  - Cooperative cancellation via exec.signal and structured error codes (UNKNOWN_TOOL, TOOL_TIMEOUT)
  - config: `mode`=native, `maxParallelSubCalls`=10
  - note: Registry that every tool (including subagent-visible tools) registers into. timeoutMs on a definition is declarative only (enforcement needs dsh-tool-call-timeout-policy); tools/pre-execute cannot rewrite exec.arguments; PTC mode rejects prompt assembly unless a loaded code runtime has a registered SDK renderer.

**`@deepseek-ai/dsh-tool-bash`** — One-shot bash tool: runs a command in a fresh shell each call and returns stdout, stderr, and exit markers. run_in_background starts long-running work inspected with job_output and stopped with job_kill; commands receive the managed DSH_* environment and sandbox denials can be retried once with wider sandbox_permissions and user approval.
  - Fresh shell per call, so cwd/variables/functions never persist
  - run_in_background for long-running commands
  - Sandbox escalation: sandbox_permissions + justification via approval
  - Non-zero exits reported as [exit code: N] markers, not tool errors
  - Output truncation to a tail with a reported spill file
  - config: `enableRunInBackground`=true
  - note: Requires an executor (dsh-bash-local / dsh-bash-sandbox) and dsh-shell-env. Opts out of timeout-policy budgets (keeps executor-owned BASH_TIMEOUT); background processes have no executor timeout.

**`@deepseek-ai/dsh-tool-bash-persistent`** — Persistent bash tool: each agent gets an isolated owner-scoped shell whose cwd, exported variables, functions, and background jobs survive across calls. Commands run sequentially; exit, timeout, or cancellation resets the shell so the next call starts fresh. Results are extracted between private start/end markers.
  - One shell per agent, cross-call state persists
  - Sequential execution with a per-owner queue
  - Marker-anchored extraction keeps prompts/echo out of results
  - Reset-never-repair on exit, timeout, send failure, or abort
  - Configurable PTY backend and per-command timeout
  - config: `backendType`=shell, `timeoutMs`=300000, `maxOutputChars`=16000, `description`=Run commands in a persistent bash shell. State, including the current directory and exported environment variables, persists across calls for this agent.
  - note: Requires an owning Agent and a real PTY backend. Interactive commands that wait for stdin are unsupported (block until timeout); no state is shared between agents.

**`@deepseek-ai/dsh-tool-pwsh`** — One-shot PowerShell tool, the Windows counterpart of dsh-tool-bash mirroring it call-for-call: each call runs a fresh pwsh -Command and returns combined output. Commands are PowerShell-dialect (native C:\ paths and $env: variables, no dialect translation); run_in_background turns long commands into background jobs. Under a sandboxing executor it teaches and enforces Windows ConstrainedLanguage and named-pipe contracts.
  - PowerShell-dialect contract: native paths and $env: variables
  - Fresh pwsh process per call; background jobs supported
  - Sandbox escalation same as bash; Windows-specific restricted-token facts taught in the description
  - Windows force-kill settles as [exit code: 1] with no signal marker
  - config: `enableRunInBackground`=true
  - note: Requires a PowerShell executor (dsh-pwsh-local) and dsh-shell-env. Session-cwd identity is not canonicalized (a parity gap with bash); there is no bash-to-pwsh translation and no persistent shell here.

**`@deepseek-ai/dsh-tool-pwsh-persistent`** — Persistent PowerShell tool: each agent keeps one owner-scoped pwsh shell that preserves cwd, $env: variables, functions, and background jobs across calls. Commands run sequentially; timeout or explicit exit discards the shell so the next call starts fresh. It installs its own prompt function carrying a BEL-terminated OSC marker for readiness and strips PSReadLine echo.
  - One pwsh shell per agent with cross-call state
  - Prompt-function readiness marker (OSC marker plus printable prompt)
  - Marker-anchored extraction strips echo and prompts
  - Reset on exit, timeout, send failure, or abort
  - config: `backendType`=shell, `timeoutMs`=300000, `maxOutputChars`=16000, `description`=Run commands in a persistent PowerShell shell. State, including the current directory and exported environment variables, persists across calls for this agent.
  - note: Requires an owning Agent and a pwsh-dialect PTY backend. PSReadLine input echo is unavoidable (stripped in complete results, may leak in partial output); raw ESC characters in commands are unsupported; a model redefinition of prompt degrades readiness to the silence tier.

**`@deepseek-ai/dsh-tool-fs`** — The read, read_image, write, and edit tools over ctx.fs: line-numbered UTF-8 reads, supported-image reads, atomic create/replace writes, and targeted literal edits. Results are capped and failures carry stable codes with recovery instructions; with dsh-fs-observation-policy mounted, writes and edits require a prior read at the unchanged version.
  - read with offset/limit pagination and cap footers
  - read_image for PNG/JPEG/WebP/GIF, extension-less files identified by signature
  - write creates or fully replaces atomically
  - edit requires a unique literal match unless replace_all
  - Stable FS_NOT_OBSERVED / FS_STALE_VERSION / FS_NOT_FOUND codes with remedies
  - config: `readLimit`=2000, `readMaxLineLength`=2000, `readMaxBytes`=51200, `readStreamMinSize`=10485760
  - note: read handles UTF-8 text only (PDF/audio/video deferred); no model-facing directory listing tool (the sibling dsh-tool-fs-search supplies glob/grep); read/write/edit take no timeout argument; image reads require an attachment store and an image-capable routed model.

**`@deepseek-ai/dsh-tool-fs-search`** — The glob file-discovery and grep content-search tools over a local workspace using a packaged ripgrep binary (no host rg install, no filesystem provider needed). Returns workdir-relative results, includes hidden and ignored files while excluding VCS metadata, and caps inline output with an optional spill store for full recovery.
  - glob and grep backed by the packaged @vscode/ripgrep binary
  - Results in modification-time order; hidden and ignored files included
  - Optional spill backend makes capped results fully recoverable
  - Structured SEARCH_INVALID_PATTERN / SEARCH_FAILED / SEARCH_RAW_OUTPUT_OVERFLOW / SEARCH_ABORTED codes
  - config: `sampleOverCapGlobResults`=none (required), `globMaxResults`=100, `grepMaxMatches`=250, `grepMaxLineBytes`=2000, `rawOutputMaxBytes`=20000000, `timeoutMs`=30000
  - note: sampleOverCapGlobResults is required with no fallback. No shared-workspace proof between search and file access; the packaged binary is fixed at the dependency version; schemas expose one bounded page (no offset pagination, no alternate output modes).

**`@deepseek-ai/dsh-tool-str-replace-editor`** — A standalone model-facing str_replace_editor tool over ctx.fs with four commands on absolute paths: view (numbered file content or shallow directory listing), create (new file, refuses overwrite), str_replace (unique literal replacement), and insert (lines at a chosen boundary). Mutations obey the same read-before-edit policy and sandbox fence as the rest of the fs family.
  - view/create/str_replace/insert command vocabulary on absolute paths
  - Numbered views preserve tabs so displayed text stays valid replacement input
  - create refuses to overwrite an existing file
  - str_replace requires exactly one unique literal match (no replace_all)
  - Composes with persistent/one-shot/sandboxed bash or terminal surfaces
  - config: `maxOutputChars`=16000, `description`=Custom editing tool for viewing, creating and editing files
  - note: Operations target UTF-8 text (binary unsupported); str_replace intentionally rejects zero or multiple matches; every mutation goes through the mounted policy and sandbox, so a deployment without them gets unconditional mutations.

**`@deepseek-ai/dsh-tool-skill`** — The session skill catalog and skill loader tool: agents receive a durable catalog of available skill names and capped descriptions before the first request, and call the skill tool to load full instructions. Users can invoke a skill with /name, which injects the same instructions into that step; catalog changes append a complete replacement, including an empty catalog that retires old names.
  - Durable pre-first-request skill catalog with capped descriptions
  - skill tool returns full instructions in a canonical <skill_content> block
  - User-explicit /name gesture injects the same rendering inline
  - Live catalog updates with complete-replacement and retirement semantics
  - Single canonical rendering shared across tool and user-invocation paths
  - config: `catalogDescriptionMaxLength`=500
  - note: Loaded instruction bodies have no size cap; resources are guidance (base dir/URL/opaque hint), not fetched attachments; catalog replacement is whole-list; bodies are not versioned so body-only edits do not change the digest.

**`@deepseek-ai/dsh-tool-web`** — The web_search and web_fetch tools over ctx.web: web_search returns an optional answer plus source URLs, web_fetch retrieves a page's content as text. Either tool can be enabled independently; external provider text is labeled untrusted, fetched HTML excludes active and hidden content, and timeout and result-size limits are deployment settings rather than model arguments.
  - Independently enableable search and fetch tools
  - Concurrent multi-query search with round-robin source merge
  - HTML-to-markdown conversion (GFM tables/strikethrough) with active/hidden content removed
  - Structured WebError (WEB_PROVIDER_UNAVAILABLE / WEB_PROVIDER_AMBIGUOUS) when a provider is missing
  - Result counts and timeouts configured as deployment settings
  - config: `search`=true, `fetch`=true, `searchMaxResults`=8, `searchMaxQueries`=4, `fetchTimeoutMs`=30000, `searchTimeoutMs`=30000
  - note: No batch-wide native-search counter (a provider can run several native searches per call); public fetches do not request approval; the model-facing API is minimal by design (max_results stays a config bound, no format/prompt/LLM-summarization mode).

**`@deepseek-ai/dsh-tool-ask-user`** — The ask_user_question tool over the user-questions seam: lets a model pause work and ask the human for confirmation, a choice, or missing information, accepting one or more questions and returning their answers as compact JSON. The call blocks until an answer is accepted or the turn is cancelled; without an accepting answerer it fails with an error.
  - One or more questions with stable ids echoed in the answer
  - Recommended option first with (Recommended) appended to its label
  - Multi-select questions return selected labels plus an optional custom answer
  - Cancellation rides the turn's exec.signal only
  - note: Runtime-owned child agents cannot call this tool (DELEGATED_CALLER) and must report the unresolved question/decision in their final result. Declares no timeout-policy budget; the package does not render or collect input, so a compatible user interaction surface is required.

**`@deepseek-ai/dsh-tool-cordis`** — Model-facing Cordis runtime tools: three read-only inspect tools (cordis_inspect_list/query/self) and four lifecycle tools (cordis_define/run/stop/undefine) that create, run, stop, update, or remove temporary dynamic packages with host code, browser code, or both. Definitions are immutable per version, exist only in process memory, and disappear when DSH restarts; the package also teaches the workflow.
  - Inspect live service methods, events, builtins, tool schemas, theme tokens, and slot trees
  - Define a new plugin or a new version of an existing plugin
  - Run/update activates a package (browser half may return awaiting-approval)
  - Stop and undefine clean up running plugins and all versions
  - @pluginId user gesture injects context pinning the plugin and update path
  - note: Session-scoped and process-local: a package affects only the session that defined it while running. The sandbox is containment for honest code, not a security boundary (treat like bash access); plain JavaScript only (no TypeScript/JSX/imports, Node globals withheld). Must be composed with dsh-cordis-host-runner; no shipped bundle mounts the toolset.

**`@deepseek-ai/dsh-tool-present`** — The present tool that declares existing files accessible through the Session filesystem as final deliverables. Users open the current source files in their default application; the tool records paths and optional descriptions without copying file contents, including files created through shell commands.
  - Works for files created via Bash or code execution
  - Relative paths resolve against the Session working directory; absolute paths may name files outside it
  - maxFiles per-call limit validated at mount
  - Files must already exist and be regular files
  - config: `maxFiles`=8
  - note: A parent must call present itself to declare files created by a subagent. Checks cannot atomically prevent replacement before a desktop app opens a file; edits change what opens; Session ZIP exports contain declarations, not file contents.

**`@deepseek-ai/dsh-tool-todo`** — The todo_write tool: a structured whole-list-replacement task list persisted on the session log. It survives across turns and reopened sessions, each update replaces the entire list, and only the owning agent session can change it. A required configuration flag allows several tasks in progress at once for parallel work.
  - Whole-list replace on every call (no partial updates or per-item edits)
  - Three statuses: pending, in_progress, completed
  - Durable log-backed state, survives replay/resume
  - Single-owner per agent session
  - Optional parallel in_progress via required config
  - config: `allowParallelInProgress`=required
  - note: Single-owner scope only: subagents and other agents each keep their own list and there is no sharing. Item shape is minimal (content + three-state status, no stable id); no read-back tool; requires an agent session to exist.

**`@deepseek-ai/dsh-tool-jobs`** — The background-job control tools job_output, job_list, and job_kill for background commands, PTY work, and subagents. Reads can wait within a configured timeout, listing identifies each job's kind and status, and cancellation settles only after the work stops. When owned work finishes the agent receives an in-session completion notice: busy agents get it injected into their next step, idle agents may be woken by a bounded follow-up turn.
  - Kind-independent controls over bash, subagent, and PTY jobs
  - job_output with optional wait and timeout cap
  - job_list with per-job kind and status
  - Completion notices with wakeup vs quiet delivery and bounded consecutive wakes
  - Producer-supplied outputLimitBytes caps the complete rendered result
  - config: `waitTimeoutMs`=30000, `maxWaitTimeoutMs`=600000, `completionDelivery`=wakeup, `maxConsecutiveWakes`=3
  - note: This plugin's controller is what arms producers' ctx.jobs.start(); an agent whose composition loads no tool-jobs cannot start background work. Stream reads are single-consumer; a notice pending on an idle owner does not survive that owner's disposal; a spent wake budget is refilled only by user-authored input.

**`@deepseek-ai/dsh-tool-goal`** — The goal tools get_goal, create_goal, and update_goal for persisted long-running objectives: read the current goal, infer and create a goal from a direct human request, and edit/pause/resume/complete/block it. Creating, editing, pausing, or resuming requires that direct request in a top-level agent turn; completing or blocking also works in an autonomous goal round, and updates require the exact goal id and revision from a prior read.
  - Compact JSON output (goal id, revision, objective, phase, rounds, cap, blocker)
  - Read-before-update refs: get_goal then copy exact goal_id and revision
  - Authority checks require a direct human message in a runtime-root turn for create/edit/pause/resume
  - resume rearms active-but-disarmed or blocked goals
  - Autonomous blocking requires the same condition for blockedAfterConsecutiveRounds rounds
  - config: `blockedAfterConsecutiveRounds`=3
  - note: Subagents and other non-human producers cannot create or edit goals; a durable paused goal is rejected on resume (GOAL_TOOL_RESUME_PAUSED) and belongs to the user-facing path. Semantic intent and same-condition blocking remain model judgment; the autonomous complete/blocked path is dormant unless a continuation driver admits goal-sourced turns.

**`@deepseek-ai/dsh-tool-call-timeout-policy`** — A cooperative tool-call timeout policy: it arms a deadline around each dispatch from the tool's own declared timeoutMs, aborts the derived exec.signal when it fires, and maps the settled timeout to a clear model error (Error: tool call timed out after <ms>ms with TOOL_TIMEOUT). Calls that finish in time are unchanged.
  - Per-tool budget read from the registry's ToolDefinition.timeoutMs
  - Signal swap onto exec for dispatch, restored in finally for post-execute listeners
  - Scoped TOOL_TIMEOUT classification so a nested outer deadline reads as an ordinary upstream cancel
  - No configuration; enabled in the dsh base bundle
  - note: Cooperative, never a hard kill: a tool that ignores the signal keeps the caller waiting and produces no timeout result until downstream settles. No blanket budget — only tools that declare timeoutMs (the shipped bash, read, write, and edit declare none) get a deadline.

**`@deepseek-ai/dsh-repeat-tool-reminder`** — An advisory loop-hygiene guard that nudges a model out of loops where it calls the same tool with identical arguments without making progress. At configured repeat counts it asks the model to inspect the previous result and change approach or finish; it never blocks or delays a legitimate repeated call. Repeats are tracked per agent and cleared by a new user message.
  - Exact-match detection via deep key-sort canonicalization (property order ignored)
  - Configured thresholds trigger short then detailed reminders
  - Per-agent chains in a WeakMap, reset on user prompts
  - include/exclude scoping, and denied calls still count
  - Advisory: rides additionalContexts, never a content replacement
  - config: `thresholds`=[3, 5, 8], `include`=[], `exclude`=[], `argumentsPreviewChars`=500
  - note: Exact-match detection only (near-identical variants evade the chain); advisory only, no blocking escalation; in-memory only so a resumed session starts fresh; chains are isolated per agent so a parent and its subagent never combine. Invalid configuration fails loudly at load.


### Sessions & persistence — 24 plugins

**`@deepseek-ai/dsh-session`** — Provides the event-sourced session log and in-memory Session store: records every model-visible fact as an append-only typed event stream and derives the model history (Message[]) from that record. Consumers create, get, list, fork, and flush sessions, inspect or replay events, and compact (hide) superseded entries without deleting them. It does not call models and stays in memory until a persistence backend is added.
  - Append-only typed SessionEvent log with snapshotJsonValue lossless validation
  - create/get/list/fork; fork cuts at a stable boundary outside an open turn
  - deriveMessages() incremental, cached projection of system/user/assistant/tool messages
  - surfaceOp append/replace semantics; replacements shadow without deleting
  - flush(session) durability barrier awaiting all persistence listeners
  - note: Core of the session subsystem; the persistent record behind every agent interaction. Requires an explicit persistence backend to become durable.

**`@deepseek-ai/dsh-session-checkpoint-policy`** — Adds semantic durability checkpoints over a session persistence backend: flushes the live session before a model request, before a top-level tool body runs, and at each agent/pre-step boundary. Checkpoint failures are fail-closed (the adapter or tool body does not run), so a crash resumes from stored requests, tool calls, responses, and results instead of losing them. It has no configuration and adds no prompt or tool schema.
  - Three checkpoint barriers: llm/stream, tools/execute, agent/pre-step
  - Fail-closed on checkpoint rejection at both model and top-level tool boundaries
  - Nested tool dispatches reuse the outer call's checkpoint
  - Interrupted tool calls recover with a TOOL_OUTCOME_UNKNOWN result, never an automatic retry
  - Listener-only, stateless policy with no configuration fields
  - note: Load beside a persistence backend for any persisted agent that can be interrupted.

**`@deepseek-ai/dsh-session-format`** — Pure adjacent Session-format planning library: restores a current Session directly or composes a unique sequence of adjacent migrations while consuming physical rows once. It provides lossless-JSON value checks, header-only classification, current artifact/header restorers, and physical codec dispatch. Physical framing, compression, immutable generation naming, and Cordis lifecycle behavior are outside this library.
  - createSessionFormatCatalog() with one frozen codec per supported version
  - readHeader() classifies current/migration-required/unsupported/malformed without reading events
  - Single-pass row restore with strict vs recoverable recovery and current vs transformed validation
  - Canonical session[.vN].jsonl basename shared by persistence/export/fixtures
  - Adjacent integer-version chain only; no general reference-rewrite algebra
  - note: Not a Cordis plugin; no profile mount row. Used by persistence/format-catalog code.

**`@deepseek-ai/dsh-session-format-catalog`** — Build-static first-party Session-format inventory: assembles codecs and adjacent migration edges from the earliest supported format through the current writer format, checks the gap-free chain at module initialization, and exposes physical dispatch, header-only classification, single-pass row restoration, and current record encoding via sessionFormatCatalog. A profile cannot add, remove, or reorder an edge by mounting a feature plugin.
  - Deterministic reader independent of mounted plugins
  - readHeader/createRestore/finish and encodeCurrentHeader/encodeCurrentEvent
  - Production reads select recoverable + transformed validation; worker/fixture reads use strict + current
  - Peer dependency on dsh-session supplies installed current vocabulary
  - Rejects duplicate codecs, duplicate edges, gaps, and beyond-current entries at construction
  - note: Imported by persistence and test-support readers before feature plugins mount.

**`@deepseek-ai/dsh-session-format-v0-to-v1`** — Frozen released-v0 Session decoder and identity migration to v1: reads the exact v0 header and packed physical rows (including packed Assistant deltas and range-encoded provenance), and produces the shared-layout v1 format applying only finite legacy normalizations accepted by v0 persistence. It accepts only the frozen first-party event inventory and refuses malformed or unknown historical records before the current restorer runs.
  - releasedV0SessionFormatCodec row-at-a-time decoder emitting scalar events or compact runs
  - sessionFormatV0ToV1 stateful stage; one stage per restore, no physical-row array retained
  - Legacy normalizers: steering→user, compact/*→compaction/*, message wrappers + deterministic ids
  - Refuses unknown events even when marked ignorable, and unexpected payload members
  - Recoverable decoding drops a faulty row and keeps the preceding prefix unless turn/end proves a commit
  - note: Obtained via the static catalog; feature compositions do not mount it directly.

**`@deepseek-ai/dsh-session-format-v1-to-v2`** — Frozen released-v1 Session reader and cardinality-changing migration to v2: consumes top-level assistant/chunk events, embeds their exact timed stream in the matching assistant/message, and records an assistant/attempt for a failed/retried/cancelled/stream-error attempt that reached settlement without a surface message. It densely remaps surviving events and every declared same-Session sequence reference, and stores one event per row deriving the inherited cut from a tagged session/end-seed marker.
  - Embeds assistant chunks into assistant/message and adds log-only assistant/attempt
  - Dense old-to-new sequence map and reference rewriting on declared reference fields
  - Closes legacy next-turn-inbox restart pattern, recording the prior turn as interrupted
  - Refuses references to a consumed chunk; keeps title-request messages byte-identical
  - releasedV2SessionFormatCodec encodes v2 headers/events one record at a time
  - note: Obtained via the static catalog; the v2 physical header requires isSeeded and stores no numeric cut.

**`@deepseek-ai/dsh-session-format-v2-to-v3`** — Complete V2-to-V3 Session conversion specification and library: promotes system prompts into messages, remaps local event references, translates PTC and preset names, canonicalizes envelopes, and preserves/refuses historical records so each historical request keeps its meaning. It is the single spec for this adjacent edge, followed separately by native V3 admission, and does not read or publish files.
  - Promotes request/header.system into system/message surface heads; empty prompts → content: []
  - Remaps sequence references, inherited cuts, PTC tag names (tool/code-dispatch → tool/ptc-dispatch)
  - Canonicalizes {op:replace,start,end} → startSeq/endSeq and drops empty header optionals
  - Refuses unknown/ignorable events, unaudited payload members, and delivery/marker violations
  - Native V3 admission separate: rejects retired header.system, noncanonical spellings, required-PTC ambiguity
  - note: Persistence consumes it through the static catalog; no Cordis mount configuration.

**`@deepseek-ai/dsh-session-persistence`** — The durable session-storage seam: a backend-independent API (create/open/stat/list/append/read/flush/close) for persisting and resuming session event logs while preserving contiguous append-only history. A completed flush is the durability barrier, readers never receive torn tails or invalid records, and one writer per session is allowed within a backend instance. The shipped JSONL backend is the concrete provider.
  - Abstract SessionPersistence service, SessionHandle contract, stable error classes, branded revision
  - create/open('write') single-writer ownership; open('read') observe-only
  - flush as the durability barrier; session/event routed into a bounded batching window
  - Crash recovery balances interrupted turns with synthetic closers on resume
  - Two shared contract suites (runPersistenceContract/runLiveWritePathContract) pin provider behavior
  - note: Seam only — providers own their storage runtime; agent-loop is the production acquisition point.

**`@deepseek-ai/dsh-session-persistence-jsonl`** — The shipped JSONL session-persistence backend: stores each session in a current append-only JSONL log and retains immutable historical format generations — checksummed Zstandard frames by default, raw newline-delimited lines when compression is 'none'. It serves the current logical event stream through persistence handles, keeping format migration, compression, historical decoding, and crash recovery internal. A root directory is the one required configuration.
  - One session-owned directory per session under a readable project directory; injective id escaping
  - Optional Zstandard frame compression; 'none' gives externally line-readable logs
  - Lazy materialization; no-overwrite publish; fsync before append resolves; rollback on failure
  - Migrates supported historical generations to current and publishes the successor without overwrite
  - Cross-process single-writer lock (flock / Windows kernel semaphore) and torn-tail recovery
  - config: `root`=required, `compression`='zstd'
  - note: Sole first-party persistence provider; live-event write batching is not configurable.

**`@deepseek-ai/dsh-session-projection`** — The session-projection registry that serves whole current values of log-derived per-session state (todos, goals, statistics) to client carriers without replaying the raw event log. Domains register synchronous projection units over committed session events; clients read complete, schema-validated JSON values via snapshots and change notifications, with asOfSeq identifying the last reflected event. Checkpoint state speeds cold reads; host-only units stay private to the host.
  - ProjectionDefinition key/schema/init/synchronous apply/optional wire/stateVersion
  - snapshot(session) consistent synchronous cut; onChanged change feed
  - Object.is change gates suppress publication across internal-only state changes
  - checkpoint/restoreFloor/restore persisted-checkpoint read recipe
  - Host-only units (no wire block) and optional registration via ctx.inject(['sessionProjections'], ...)
  - note: Service Definition + drive role: the framework drives, the domain computes. Registry cells are in-memory only unless session-projection-cache is mounted.

**`@deepseek-ai/dsh-session-projection-cache`** — Persists per-session projection checkpoints so history lists, statistics, and goal snapshots read cached values without loading each session log, and cold projection folds resume after the checkpointed prefix. The session log stays authoritative: a crash can leave a checkpoint stale but never ahead of committed events, and incompatible records are ignored or backed up.
  - Three mandatory write points: session creation, turn/end, disposal; count/interval throttles between
  - cachedSnapshot(meta, inheritedEventCount) zero-I/O in-memory read with version/schema matching
  - cachedPredecessorTitle listing-only exception carrying asOfSeq: -1
  - Log leads, cache follows: live checkpoint flushes session buffer before the cache row lands
  - Backup-and-skip salvage of invalid records as <id>.json.bak.<stamp>
  - config: `writeEveryEvents`=required, `writeIntervalMs`=required
  - note: Requires storage, storage-json, and storage-domain (backend: json) mounted below it.

**`@deepseek-ai/dsh-session-query`** — Unified session-history query service: list, filter, read, and search session history, inspect bounded event context, and trace session or event relationships. Reads prefer live sessions over persisted copies and return detached clones from one consistent observation. Exact reads, filters, and traces work with any storage setup; ranked full-text search requires a mounted backend such as dsh-session-query-sqlite.
  - listSessions/readSession/filterSessions/filterEvents/readTitleSnapshots/listEvents/readSurface
  - readEvent bounded raw-log window; traceSession lineage; traceEvent replacements/citations
  - Live-preferred corpus resolution with immutable-header conflict detection
  - Typed SessionQueryError codes (SESSION_QUERY_* taxonomy)
  - searchSessions/searchEvents are the only abstract surface a backend owns
  - config: `readWindowMax`=50, `persistedReadConcurrency`=4, `preparedSessionCacheSize`=5
  - note: Never mounted alone; provided by a concrete backend plugin (shipped: dsh-session-query-sqlite). Trusted infrastructure — no caller authorization.

**`@deepseek-ai/dsh-session-query-sqlite`** — SQLite FTS5 full-text search backend for session history: indexes live and persisted history in a separate derived database and adds ranked, cursor-paginated search across or within a session. Exact reads, filters, and traces remain available through the same query API. Search is opt-in via openAt, and each index path has a single process owner.
  - searchSessions (whole corpus) and searchEvents (one session) with cursor pagination
  - Deterministic ranking by highlight spans, then shorter docs, then time/id/seq
  - Literal-phrase quoting keeps FTS5 syntax inert (quotes, OR, NEAR, * are data)
  - Generation-bound cursors fail stale instead of shifting a page
  - Derived index never touches the session-persistence database; owner-only file creation
  - config: `path`=required, `openAt`='startup', `journalMode`='wal', `defaultLimit`=20, `maxLimit`=100, `snippetChars`=240
  - note: unicode61 tokenizer matches tokens/phrases, not substrings; use filterEvents() for literal scans.

**`@deepseek-ai/dsh-session-reference`** — Lets a conversation reference other sessions: a host turns a @label mention into a canonical dsh-session: URI, and the service prepares a bounded, read-only snapshot of each referenced session as durable, untrusted background context for the model. Candidate discovery ranks sessions by working-directory affinity and labels them with their latest titles; snapshots carry a fixed warning forbidding following instructions, permission claims, or tool requests inside them.
  - Canonical mention syntax @[label](dsh-session:<base64url-id>) or bare dsh-session: URI
  - Prepares a ## Referenced sessions second user-role message with fixed untrusted-background warning
  - Bounded per-source JSON byte budget and maxReferences per message
  - Optional spill backend for full transcript; omission notices with exact counts
  - listCandidates(agent, query?, limit?) ranking same-directory sessions first
  - config: `maxReferences`=3, `candidateLimit`=50, `maxReferenceBytes`=automatic, `referenceContextFraction`=0.2
  - note: Opt-in service consuming ctx.sessionQuery; no SQLite FTS needed. Auto budget is max(65536, floor(contextWindow × 4 × referenceContextFraction)).

**`@deepseek-ai/dsh-session-stats`** — Whole-log conversation counts and wall times exposed as the sessionStats projection unit: turn and step counts plus LLM, tool, first-token, and decode wall times, derived from the complete durable log so paging and compaction do not change them. Clients render whole-session statistics consistent across reloads and reduced history; a window-scoped fallback exists when whole-session figures are unavailable.
  - Eight totals: turns, steps, llmMs, toolMs, ttftMs/ttftSteps, decodeMs/decodeTokens
  - Folds step/end exactly once per entered step (finally), covering failed/cancelled/max-tokens
  - Pairs tool/call → tool/result by callId; unresolved calls dropped at turn/end
  - Inert without the projection registry; registers on the mounting fiber and removes with it
  - note: Counts are log-scoped, not surface-scoped; cancelled steps count but are untimed.

**`@deepseek-ai/dsh-session-telemetry`** — Session-telemetry capture seam: sends ordered copies of session activity to a reporting backend while preserving the canonical session log, with optional per-copy redaction before delivery. One backend plugin is chosen (live or on-demand capture), the handoff is non-blocking so reporting never delays session processing, and delivery is best-effort — queued records may be lost on crash.
  - Backend contract: emit (non-blocking), optional flush hint, shutdown drain
  - live capture follows appends + replays live sessions; on-demand reads the canonical log prefix
  - One ledger record per canonical event, carrying id, format_version, seq, severity
  - Redaction via sessionTelemetry/record waterfall; with no listener, records leave unchanged
  - sharing disclosure: full, feedback-only, or disabled
  - note: Ships no redaction rules; deployments own the rule set. Best-effort delivery (no durable outbox).

**`@deepseek-ai/dsh-session-telemetry-otel`** — OpenTelemetry session-telemetry backend: exports session records through the OTel JS SDK only after new explicit feedback (FEEDBACK_ONLY) or not at all (DISABLED). FEEDBACK_ONLY releases the canonical prefix through that feedback including context, and later records wait for the next explicit feedback; DISABLED constructs no transport. SDK batching can finish an authorized upload without another interaction, and deployments own their redaction rules.
  - FEEDBACK_ONLY / DISABLED modes; FULL is rejected, not an alias
  - Exporter URL and SDK option blocks (exporter, processor) passed verbatim
  - Complete event.data leaves (messages, tool args/results, system prompt, schemas, cwd); provider API keys structurally absent
  - Fail-closed config validation at plugin load; outer shutdownTimeoutMillis deadline
  - Only new own feedback/record, feedback/message-put, feedback/message-delete trigger live capture
  - config: `mode`='FEEDBACK_ONLY', `exporter.url`=required in uploading modes, `exporter`=—, `processor`=—, `shutdownTimeoutMillis`=3000
  - note: Reports resource identity service.name/version + anonymous user.id once per batch. No durable outbox; receivers dedupe by (session id, format version, seq).

**`@deepseek-ai/dsh-session-title`** — Log-backed session titles: gives each session a client-visible title from the first eligible human message (deterministic fallback), an optional asynchronous provider, or an explicit user rename. Accepted titles persist through replay, resume, and paging but never enter model input; automatic generation never delays the main agent response, and newer title requests supersede older work.
  - Three sources, newest wins: fallback, provider, explicit rename
  - Fallback from first eligible human message's leading words within configured caps
  - Session/title is log-only; never reaches the surface, deriveMessages, or system prompt
  - refresh(session) explicit regenerate path; user-sourced title pins the session until refresh
  - Registers title (client) and titleInput (host-only O(1) fold) projection units
  - config: `fallbackMaxWords`=required, `fallbackMaxBytes`=required, `maxTitleBytes`=required
  - note: At most one provider may be registered; requires ctx.sessionProjections.

**`@deepseek-ai/dsh-session-title-first-prompt-llm`** — First-message LLM session-title provider: summarizes the first eligible human message through ctx.llm as an optional ctx.sessionTitle provider. It registers the first-prompt cadence, runs automatically only when a fresh non-fork session first creates its fallback, and attributes the result to that message's exact seq. An automatic failure retains the fallback and retries only via ctx.sessionTitle.refresh().
  - Registers the first-prompt cadence with a first-eligible-message selector
  - Automatic only for fresh, non-fork sessions with no prior title
  - Uses the complete required shared LLM config from dsh-session-title-llm (no defaults)
  - Auxiliary request adds no tokens and no latency to the main agent request
  - Forks keep inherited title and never run this provider automatically
  - config: `targetWords`=required, `targetCjkCharacters`=required, `maxInputBytes`=required, `maxOutputTokens`=required, `timeoutMs`=required, `provider`=optional
  - note: Thin registration over the shared LLM title policy; omit provider/model to inherit the logged main request route.

**`@deepseek-ai/dsh-session-title-llm`** — Shared model-backed title generation policy: generates concise session titles from selected human messages with a consistent model request policy. Callers choose which messages contribute to each revision and either supply a provider/model route together or use the route recorded for the current session; required limits cap framed input, generated output, and duration, and caller cancellation stays effective throughout streaming. Invalid, empty, late, tool-call, or non-text results are rejected before they can replace a title.
  - registerSessionTitleLlmProvider(ctx, config, id, automatic, selectMessages) helper
  - Route resolution: explicit pair or the session's logged request/header
  - Measures final JSON-framed prompt against maxInputBytes before dispatch (no truncation)
  - Logs a log-only session/title-llm-request carrying the exact dispatchable request
  - Rejects tool calls, malformed/empty output, and non-stop finish reasons; purpose 'session-title' disables thinking on DeepSeek
  - config: `targetWords`=required, `targetCjkCharacters`=required, `maxInputBytes`=required, `maxOutputTokens`=required, `timeoutMs`=required, `provider`=optional
  - note: Configured through the first-prompt or all-prompts provider plugin, not mounted directly.

**`@deepseek-ai/dsh-session-turn-outline`** — Whole-log turn outline exposed as the turnOutline projection unit: a session-wide outline of every started turn with bounded prompt and settled-response previews, so history clients can navigate turns not yet loaded and page backward from the exact event seq needed to load a selected turn. Previews exclude injected context and tool results, and a response appears only after its turn settles.
  - Entries anchored on turn/start seq (the load-through target for a jump)
  - Prompt preview from first human user/message (50-char cap); response preview at turn/end (120-char cap)
  - Prompt fills only from human-source user/message, so injected context and tool results never leak
  - Strictly increasing by turn; whole-value rule — consumers replace, never merge
  - At most three change-feed pushes per turn (boundary, prompt, settled response)
  - note: Inert without the projection registry; wire value grows with the session (whole-value rule).

**`@deepseek-ai/dsh-session-log-deepseek`** — Incremental canonical session-log upload for official DeepSeek LLM API requests: owns the dsh_session_log request field and the durable session-log-deepseek/delivery-accepted event from which it derives the acceptance watermark. Enabled only when the official API should receive a Session-log suffix; it injects ctx.sessions and ctx.deepseekLlmApiExtensions.
  - Registers dsh_session_log request field when enabled
  - Folds the greatest accepted watermark for the exact Session format generation and sends the contiguous suffix
  - Accepts after HTTP 2xx (before SSE body consumption); appends delivery-accepted with throughSeq
  - Forked sessions ignore inherited parent watermarks; transport/non-2xx failures resend the uncertain range
  - No independent I/O — the session checkpoint policy persists the watermark at the next semantic checkpoint
  - config: `enabled`=false
  - note: At-least-once failure direction: crash-window duplicates, never a skipped sequence.

**`@deepseek-ai/dsh-session-log-export`** — Web Session-log ZIP export: lets the browser download a session's full history via a Download session log menu item under the Session Header and an /export slash command, handing the session tree (session, sub-sessions, attachments) to the browser as a ZIP. It owns the Host archive stream, the authenticated Fetch route, and the browser controls and feedback; the browser chooses the destination.
  - /export command and Download session log menu both produce dsh-session-<id>.zip
  - Host endpoint flushes a live root session before reading; cold sessions need no flush
  - One in-flight download per session; concurrent gestures share the operation
  - Canonical session.vN.jsonl filenames per sub-session; media/ and files/ attachment paths
  - Generic-file bytes compressed as bounded chunks, so large uploads are not fully buffered
  - config: `compressionLevel`=6
  - note: Browser download only, not a Host-path writer; serialized from persistence read handles so any mounted backend is supported.

**`@deepseek-ai/dsh-message-feedback`** — Records canonical Session-log ratings, categories, and notes for finalized assistant messages. The Session log owns every creation, edit, and deletion; list, put, and delete expose current feedback without constructing or waking an Agent. Feedback is log-only and does not enter model history.
  - Positive/negative rating, optional fixed-taxonomy category, optional verbatim note
  - Optimistic concurrency via expected version; no-op puts return the same item without appending
  - Targets must be non-empty append-origin assistant messages; replacement-origin returns target-not-found
  - Feedback survives restart; forks start without owned feedback
  - maxNoteBytes enforces one note; note validation precedes Session lookup
  - config: `maxNoteBytes`=required
  - note: Requires sessions and sessionPersistence. Existing message_feedback sidecar data is neither read nor migrated.


### Goals, schedule, compaction — 14 plugins

**`@deepseek-ai/dsh-goal`** — Persists one same-session completion objective across turns, session resume, fork, and process restarts, and serves it to consumers through a compare-and-set service. It stores goal state (phase, round count, revisions) in the session log as durable events but does not schedule any work.
  - Durable phases active/paused/blocked/complete plus a process-local armed/disarmed flag
  - Compare-and-set mutations reject stale revisions with a clear error
  - Configurable round cap bounds automatic continuation
  - Blocked goals retain a stable policy code plus a human-readable explanation
  - State survives resume/fork; continuation is re-armed only by an explicit resume
  - config: `defaultMaxGoalRounds`=256
  - note: Session-scoped; model-facing goal tools live in dsh-tool-goal, not here.

**`@deepseek-ai/dsh-goal-round-driver`** — Automatically continues an active, armed goal in the same session while the agent is idle and the round allowance remains, queuing one goal-round prompt per round. It records a round-limit blocker on exhaustion and takes no configuration.
  - Each round gives the model another turn toward the objective
  - Only goal rounds that reach model history consume the allowance
  - Stops on completion/pause/block, max-token turns, durability failures, and cancellation
  - Never auto-arms a goal after resume or fork
  - Exhaustion records a blocker with the stable code round-limit
  - note: Host-composition driver; the goal defines the round limit and dsh-tool-goal defines the blocked threshold.

**`@deepseek-ai/dsh-command-goal`** — Adds the human-facing /goal slash command to create, edit, pause, resume, clear, and inspect the current goal without a model turn. Commands and their direct output stay in the UI command plane, and attachments on a create or edit become one ordinary user message.
  - Bare /goal shows objective, phase, round count/cap, and valid next commands
  - /goal <objective> creates and arms a goal, or replaces a completed goal
  - edit, pause, resume, and clear lifecycle sub-commands
  - Expected domain rejections become stable direct command errors
  - Web command adapter only among shipped apps
  - note: Requires a command adapter; headless, ACP, and JSON-RPC entry points have none.

**`@deepseek-ai/dsh-schedule`** — Adds durable session-local reminders the model creates through schedule_create, schedule_list, and schedule_delete tools; due reminders return as ordinary follow-up messages in the same conversation. Reminders survive restarts, but delivery requires a live root agent and never uses email, SMS, push, or browser notifications.
  - One-time (delay or absolute time) and fixed-interval (at least 5 minutes) reminders
  - Stable error codes for empty prompts, invalid zones, non-future or out-of-range times
  - Strict replay from session-log schedule/change events
  - Latest-only catch-up for missed intervals
  - Optional strict schedule session-projection unit
  - note: Tools install on root Agents only; runtime children never receive Schedule.

**`@deepseek-ai/dsh-command-compact`** — Adds an on-demand /compact command that condenses an older balanced span of the conversation into one summary even below automatic pressure, and reports the condensed item count and estimated tokens saved. It works with any condensation backend and consumes no model turn.
  - Condenses without waiting for automatic pressure
  - Reports replaced item count and estimated tokens
  - Stable messages for each expected failure (busy, history changed, no summary, unsaved)
  - Prompts sent while it runs are queued and start after it finishes
  - Idle-only and argument-free
  - note: Requires a command adapter and a mounted CompactionEngine backend.

**`@deepseek-ai/dsh-compaction`** — Defines the shared condensation contract that backends implement and triggers use: the abstract CompactionEngine, the log-only compaction/* events, and a condensed-message marker for recognizing condensed history. It performs no condensation itself.
  - Three backend operations: compactIfNeeded, compactNow, compactRegion
  - Log-recorded compaction/start -> summary -> end bracket acts as the durable lock
  - Surface is mutated exactly once via a user/message replacement
  - Exported condensed-message marker for recognizing history
  - Closed-union surface events; compaction/* never appears on the surface
  - note: Mount the shipped backend (dsh-compaction-basic) to get the feature working out of the box.

**`@deepseek-ai/dsh-compaction-basic`** — Automatically condenses older history into one summary as token pressure builds, and recovers after a confirmed context-window-overflow error by condensing and retrying. It also serves the /compact command and optional tool-result pruning, using one extra model request and retaining only the summary text.
  - Condenses at thresholdRatio of the routed context window
  - Keeps the newest retainRatio verbatim
  - Per-model policy overrides via modelPolicies
  - Overflow recovery with configurable retries
  - Replays the warm prefix to reuse the provider's cache
  - config: `thresholdRatio`=0.8, `retainRatio`=0.16, `retainTokens`=none, `summarizationProvider`='', `summarizationModel`='', `maxTokens`=8192
  - note: Cannot shrink the system prompt, tools, or session prefix, nor split one indivisible unit such as a single huge tool call.

**`@deepseek-ai/dsh-compaction-tool-result-pruner`** — Trims oversized tool-result text when a compaction trigger qualifies, replacing over-budget content with a bounded head, a 'middle pruned' marker, and a bounded tail. The complete original stays in the session log; trimming makes no model call and may relieve enough pressure to skip summarization.
  - Replaces text only, keeping tool call, step, errors, metadata, and rich-block order
  - Deterministic Unicode code-point slicing that never splits a surrogate pair
  - compaction/prune shadow-price event precedes each replacement
  - Runs only after a compaction trigger qualifies; below-pressure history is untouched
  - Head plus marker plus tail must fit within thresholdChars
  - config: `thresholdChars`=8192, `headChars`=4096, `tailChars`=1024
  - note: Character budgets only approximate token use; the token meter decides whether pressure was relieved.

**`@deepseek-ai/dsh-time-context`** — Appends a durable, source-attributed clock reading with the current time, the browser zone attached to the open request, and elapsed time on eligible steps, so the model can interpret unqualified dates and times in the user's zone. It is opt-in and mounted by the Schedule Web overlay.
  - Three-line reading: ISO timestamp with offset and IANA zone, browser-zone policy, elapsed duration
  - Uses the request-local browser zone when unique, else a configured fallback
  - refreshIntervalMs reduces how often readings accumulate
  - Tells the model to ask for clarification when zone provenance is mixed or missing
  - Backward wall-clock movement clamps elapsed time to zero
  - config: `timeZone`=process zone, `refreshIntervalMs`=0
  - note: Prompt provenance only; does not silently supply another tool's required zone field.

**`@deepseek-ai/dsh-tmux-context`** — Appends a durable, source-attributed reading of the tmux session, window, pane, and pane-tree layout on the first step of a turn, only when that location changed. It is opt-in and not included in the shipped Web or headless profiles.
  - Reports session name, window index and name, pane index and id, active flags, and compact pane-tree layout
  - Injects only when the tmux state changed since the last injection
  - tty-based detection excludes terminals that merely inherited tmux environment variables
  - Failed or malformed queries add nothing and never fail the turn
  - Pixel sizes and sibling-pane contents are excluded
  - config: `refreshIntervalMs`=0
  - note: Requires the agent process to run inside tmux with a controlling terminal matching the pane.

**`@deepseek-ai/dsh-token-meter`** — Estimates a session's current request and context pressure and prices individual messages by replaying the durable session log deterministically and with no model calls. It exposes measure()/estimateMessage() and, when session projections exist, the tokenUsage, contextPressure, and contextBreakdown units.
  - Replay-based, deterministic, allocation-fresh measurement
  - measure() returns totalTokens, surfaceTokens, and per-node tokens
  - Fixed four-characters-per-token heuristic, plus route image pricing when declared
  - Provider-reported usage reused only for an identical request envelope
  - Projection units for compaction, occupancy displays, and telemetry
  - note: No settings; consumed by compaction and occupancy UIs; the heuristic underprices CJK text and JSON schemas.

**`@deepseek-ai/dsh-timeout`** — Provides shared timeout arithmetic, deadline fusion, and timeout-versus-cancel classification: clampTimeout fills and caps a caller's hint, deadline fuses a local timer with upstream cancellation, and idleWatchdog counts only time spent waiting on provider reads. It is a library imported directly, not a cordis.yml plugin.
  - clampTimeout fills a backend default, caps at the max, and rejects invalid hints
  - deadline fuses the timer and upstream abort via AbortSignal.any
  - timeoutOf classifies local timeout versus upstream cancellation under nesting
  - idleWatchdog arms only while an iterator next() is outstanding
  - Notification only; the caller owns the actual termination path
  - note: Local file read/write/edit run untimed by design; timeoutMs <= 0 is backend-internal vocabulary, not a public knob.

**`@deepseek-ai/dsh-command-feedback`** — Records session feedback through the /feedback command and the sessionFeedback Host Remote behind the Web dialog, both filing under a fixed seven-category taxonomy. Recording is immediate and append-only, never starts model work, and never enters a model request.
  - /feedback <remark> records and acknowledges the session id and anonymous user id
  - Web dialog records a category and optional description via sessionFeedback.record
  - Fixed taxonomy: task-result, instruction-following, product-interaction, service-stability, resource-cost, security-privacy-permission, other
  - Any UI, hook, or host integration can call recordFeedback
  - Remark stored exactly as typed; each entry is independent
  - note: Append-only with no retrieval/amend/withdraw; the acknowledgement follows the append, not a flush barrier.

**`@deepseek-ai/dsh-output-retention`** — Caps how many items or how much text a tool returns to the model while honestly reporting what was omitted, via ItemRetainer and TextRetainer plus a standardized omission footer. It is imported directly by tools such as glob, grep, bash, web_fetch, and web_search rather than loaded through cordis.yml.
  - ItemRetainer keeps an ordered head window and can report an exact omitted-item count
  - TextRetainer keeps head, tail, or head-tail byte windows
  - formatRetentionNotice adds a standard omission clause plus tool-owned recovery guidance
  - Never returns invalid UTF-8 cuts at the boundaries
  - truncated is a budget fact, never an upstream-completeness claim
  - note: Item retention is head-only; read tool pagination stays outside this library.


### FS, shell, sandbox, subprocess — 24 plugins

**`@deepseek-ai/dsh-fs`** — The ctx.fs filesystem service contract: resolves any path to a stable target identity, reads text/bytes (bounded), lists one directory level, and applies atomic text writes and literal edits through a pluggable backend. A backend owns identity, execution-world coordinates, decoding, binary rejection, and atomicity; policy stays off the base class.
  - Abstract FileSystem service registered as ctx.fs; backends register via the seam
  - Stable FsTarget identity: the same file via different paths yields the same opaque targetKey
  - Typed FsError with stable codes (FS_NOT_FOUND, FS_STALE_VERSION, FS_AMBIGUOUS_EDIT, FS_TOO_LARGE)
  - Optional version guard on write/edit; readBytes requires maxBytes and never truncates
  - Emits fs/* policy events (write-intent, edit-intent, observed) shared with the observation-policy plugin
  - note: Service definition only; mount fs-local, fs-sandbox, or fs-e2b to populate ctx.fs. Text-only mutations by contract; no delete/rename/copy/watch.

**`@deepseek-ai/dsh-fs-local`** — Host-filesystem backend for ctx.fs: reads, lists, atomically writes and edits files on the real host filesystem, with realpath identity, permission-preserving atomic replacement, and optional version guards. Relative paths resolve from a configurable base; absolute paths and parent traversal stay unrestricted.
  - Realpath identity: symlinked paths to one file share one targetKey; writes land on the link target
  - Atomic publication (staging temp + fsync) with mode and Windows DACL preservation; per-target FIFO lock serializes mutations
  - config.cwd is a resolution default, not a containment boundary
  - Guarded create uses hard-link no-replace publication (FS_NOT_OBSERVED on concurrent creator)
  - Typed FsError codes; diffBasisMaxBytes bounds the overwrite-diff basis
  - config: `cwd`=process.cwd(), `diffBasisMaxBytes`=10 MiB

**`@deepseek-ai/dsh-fs-sandbox`** — Sandbox-enforcing ctx.fs backend: confines model file writes and edits by the session's sandbox mode (read-only / workspace-write / danger-full-access) while reads stay unconfined; denied mutations return FS_SANDBOX_DENIED. It extends fs-local and adds only the mode fence.
  - Fence applies per call; same mode and workspace root as the bash runner via shared policy
  - read-only denies every mutation; workspace-write allows only targets canonicalizing under the workspace root or a platform temp area
  - danger-full-access delegates unfenced
  - Denied mutation surfaces [sandbox: file access denied under <mode> mode] plus the same-turn escalation hint
  - Re-canonicalizes the target immediately before the mutation to narrow the resolve-to-syscall TOCTOU
  - config: `cwd`=process.cwd(), `diffBasisMaxBytes`=10 MiB
  - note: Policy fence in trusted code, not a kernel boundary; kernel-grade isolation of untrusted code stays ctx.shell's job.

**`@deepseek-ai/dsh-fs-observation-policy`** — Read-before-edit filesystem policy: requires the agent to read a file before overwriting or editing it, and rejects a mutation when the file changed since that read (FS_STALE_VERSION), returning a clear re-read-and-retry instruction. Reading a missing path authorizes guarded creation.
  - Event-gate plugin over the fs/* events; registers no ctx.fsPolicy service and has no public methods
  - Records observed state (unseen / confirmed absent / present at a version) per owner and target
  - Reading a missing path marks it confirmed absent, so a later write may recreate it through the guarded-create flow
  - Unobserved edit fails FS_NOT_OBSERVED; editing an observed-absent target fails FS_NOT_FOUND
  - Observations are not persisted — a resumed session must re-read targets before guarded mutations
  - note: Authorization is version freshness, not view completeness: any windowed read authorizes a full-file overwrite of an unchanged file.

**`@deepseek-ai/dsh-shell`** — The bash executor seam: ctx.shell runs foreground shell commands with bounded output or starts background processes that return a handle immediately. resolve() turns a request into a fully-resolved spec with explicit cwd, timeout, and output limits before anything runs.
  - resolve() is the single place defaults and caps are applied; run/start accept only resolved specs
  - Nonzero exit, executor timeout kill, and caller abort are results; only infrastructure failures reject
  - start() returns a task-free ShellProcess handle; readOutput() is consuming and lossy reads point at spill files
  - Shared exit-status marker contract ([exit code: N] / [killed by signal: X]) and parseExitStatus helper
  - Mount exactly one executor per composition; the bash and pwsh tools build on the seam
  - note: Service definition; POSIX providers are dsh-bash-local and dsh-bash-sandbox, Windows counterparts dsh-pwsh-local and dsh-pwsh-sandbox.

**`@deepseek-ai/dsh-shell-env`** — Provides the trusted DSH_* environment every model shell call (bash or pwsh) runs with: built-in facts such as DSH_HOME, DSH_SHELL=1, and DSH_SESSION_ID, plus a registry for plugins to declare and register their own DSH_* facts per execution.
  - Built-ins DSH_HOME, DSH_SHELL=1, and DSH_SESSION_ID (for agent calls)
  - Plugins register contributors that declare keys; duplicate ownership or claiming a reserved built-in fails load loudly
  - Inherited DSH_* values are discarded and the registry snapshot is rebuilt per call; process.env is never modified
  - Registration is disposed with the registering plugin (HMR-safe)
  - Keys must be all-caps with underscores and carry a description; list() enumerates plugin-contributed variables only
  - config: `dshHome`=$DSH_HOME, then ~/.dsh
  - note: Load in any composition that mounts a model shell tool; configuration only picks the Harness home.

**`@deepseek-ai/dsh-bash-local`** — Default POSIX Bash executor: every command runs as a fresh non-login bash -c process with no rc files, so no shell state survives between calls. It applies configured budgets (working directory, timeout, output caps), classifies timeouts/cancellations, and returns bounded output with spill-file recovery; it confines nothing.
  - Fresh non-login bash -c per call; deterministic and state-free
  - Budgets from config; per-call timeout overrides capped by maxTimeoutMs
  - maxOutputBytes in-memory cap spills to a temp file; maxSpillBytes caps full spill
  - Model-friendly env (NO_COLOR=1 TERM=dumb PAGER=cat GIT_PAGER=cat); explicit caller env still wins
  - Background start() with consuming readOutput(), kill(), and never-rejecting done; POSIX-only
  - config: `cwd`=process.cwd(), `timeoutMs`=120,000, `maxTimeoutMs`=600,000, `maxOutputBytes`=64,000, `maxSpillBytes`=67,108,864, `graceMs`=3,000
  - note: Commands run with the harness process's own authority; compose dsh-bash-sandbox when confinement is needed.

**`@deepseek-ai/dsh-bash-sandbox`** — Sandbox-consuming Bash executor: runs each bash command with file-access confinement instead of the harness process's full authority, reporting the selected mode, denied file operations, and enforcement completeness. If no runner can enforce a confined mode, the call fails with SANDBOX_UNAVAILABLE rather than running unconfined.
  - Modes: read-only (default, /dev/null writable), workspace-write (workspace + temp), danger-full-access (unconfined)
  - Requires ctx.sandbox plus ctx.sandboxPolicy; tools advertise sandbox_permissions/justification escalation fields
  - Denied command is reported as sandbox: { mode, denied: true }; tool appends the denial marker and escalation hint
  - Fail-closed: a confined mode with no usable runner throws SANDBOX_UNAVAILABLE, never a silent unconfined run
  - File effects only — network stays unrestricted and process visibility is backend-specific
  - config: `cwd`=process.cwd(), `timeoutMs`=120,000, `maxOutputBytes`=64,000
  - note: Deny-only at the seam: it never grants permission; the approval flow lives in the tool layer.

**`@deepseek-ai/dsh-pwsh-local`** — Local PowerShell executor: every command runs as a fresh non-interactive pwsh -Command process with no profile files, mirroring dsh-bash-local's semantics call-for-call and adding pwsh-specific executable resolution, UTF-8 output pinning, and the model-friendly terminal environment. It confines nothing.
  - Fresh pwsh -NoLogo -NoProfile -NonInteractive -Command per call; no profile state leaks
  - Resolves pwsh from pwshPath, well-known Windows install locations, PATH, then Windows PowerShell 5.1
  - Command rides as one -Command argument, so no intermediate shell-quoting layer to escape
  - Pins UTF-8 output so non-ASCII is not garbled even on the 5.1 fallback
  - Same budget fields as bash-local; registers the capability's shared shell settings namespace
  - config: `cwd`=process.cwd(), `timeoutMs`=120,000, `maxTimeoutMs`=600,000, `maxOutputBytes`=64,000, `maxSpillBytes`=67,108,864, `graceMs`=3,000
  - note: Windows counterpart of dsh-bash-local; swap the POSIX rows for the pwsh rows to keep the same semantics.

**`@deepseek-ai/dsh-pwsh-sandbox`** — Sandbox-consuming PowerShell executor: runs each pwsh -Command confined through the ctx.sandbox capability with the selected mode, enforcement, and denial facts stamped on each settled result. On Windows the seam resolves to the ACL restricted-token runner chain; on Linux/macOS it uses bwrap, Landlock, or Seatbelt. It fails closed with SANDBOX_UNAVAILABLE when no runner can enforce a confined mode.
  - pwsh twin of dsh-bash-sandbox, mirroring it call-for-call
  - Windows uses the ACL restricted-token runner chain; Linux and macOS use the local runner provider
  - Denials surface as sandbox: { mode, denied: true } and the standard permission-denied plus escalation surface
  - Fail-closed SANDBOX_UNAVAILABLE if no runner enforces a confined mode; never a silent unconfined run
  - danger-full-access bypasses ctx.sandbox entirely and stamps denied: false
  - config: `cwd`=process.cwd(), `timeoutMs`=120,000, `maxOutputBytes`=64,000
  - note: Requires a ctx.sandbox provider plus ctx.sandboxPolicy; mode and workspace root ride each call, not this package's config.

**`@deepseek-ai/dsh-sandbox`** — Process-sandbox service contract: wraps a subprocess and everything it spawns under a per-call file-access policy (read-only / workspace-write / danger-full-access). If the requested mode cannot be enforced, the call fails with SANDBOX_UNAVAILABLE instead of running unconfined. This is same-world confinement; the process still shares the host kernel and filesystem.
  - SandboxPolicy rides each call, never fixed on the provider; escalation is a new call with a wider policy
  - Fail-closed: confine() returns enforcing argv or throws SandboxUnavailableError; silent unconfined passthrough is forbidden
  - One shared denial/escalation vocabulary so the bash and fs families cannot drift
  - Escalation ladder is a closed table (read-only→workspace-write|danger-full-access; workspace-write→danger-full-access)
  - writableRoots derives the workspace-write allow-list, shared by the Seatbelt profile and the in-process fs fence
  - note: Same-world by contract; containers, microVMs, and remote execution replace the surrounding capability seam instead.

**`@deepseek-ai/dsh-sandbox-local`** — Local per-platform sandbox backends: automatically chooses a supported runner chain (bwrap then Landlock on Linux, Seatbelt on macOS, ACL restricted-token on Windows) and reports full or partial enforcement plus denial and runner-failure signatures. It fails with SANDBOX_UNAVAILABLE when none is usable, so commands never silently run without confinement.
  - Runner selection by platform first, functional probes second; first usable verdict cached for provider lifetime
  - bwrap profile: read-only host root, fresh /dev, private-PID /proc; workspace-write adds ephemeral /tmp and a writable bind
  - Reports enforcement: full or partial (Windows ACL rung, older Landlock ABIs are the current partial cases)
  - runnerCommand override: an operator assertion that skips probes and requires runnerFailureSignatures
  - Per-platform denial and runner-failure dialects carried on each wrap for classification
  - config: `runnerCommand`=[], `runnerFailureSignatures`=[], `probeTimeoutMs`=5,000
  - note: Seatbelt depends on the deprecated sandbox-exec; runner selection is cached for the provider lifetime, so changes need a reload.

**`@deepseek-ai/dsh-sandbox-policy`** — Shared per-call sandbox policy resolver: owns the deployment default mode and fallback workspace root plus the per-session overrides that enforcing capabilities consume, and contributes the current policy to the model's runtime-context snapshot so all enforcing capabilities use the same mode and workspace for a call.
  - Resolution precedence: approved explicit grant > session's last sandbox/mode event > deployment default
  - Session mode switches survive restart via log-only event replay; each session keeps its own mode
  - Session immutable cwd is canonicalized as the workspace-write boundary
  - sandbox:policy context clause states the mode and workspace without enumerating mounted capabilities
  - Invalid configured mode is rejected at plugin load so a typo fails loud
  - config: `mode`=read-only, `workspaceRoot`=process.cwd()
  - note: File-effect modes only; network and process policy are outside its vocabulary.

**`@deepseek-ai/dsh-sandbox-windows-acl`** — Windows write-restriction sandbox backend: confines child-process writes to the workspace and a private temporary directory using a WRITE_RESTRICTED token with a deterministic workspace SID (standing ACE) and a revocable temp SID. Writes are restricted; reads, network, and process visibility are not; the guarantee is intentionally partial.
  - WRITE_RESTRICTED token: write-class access granted only where normal and restricting SID checks both pass
  - workspace-write grants workspace + private temp; read-only grants neither
  - Deterministic workspaceWriteSid (standing, once per workspace) + random tempWriteSid (revocable, per live session/workspace pair)
  - init() throws on any Win32 failure — the child is never spawned unrestricted; reports enforcement: partial
  - Public AclSandbox direct API to spawn confined children outside the harness (requires explicit tempDir)
  - note: No plugin config table; the direct AclSandbox API takes writableDirs, tempDir, writeSid, tempWriteSid, and mode. Mounting dsh-sandbox-local selects this backend automatically for confined bash/pwsh on Windows.

**`@deepseek-ai/dsh-subprocess`** — Subprocess service (ctx.subprocess): resolves executables, starts explicitly specified child processes or real terminal sessions, streams or collects bounded output, and terminates the full managed process range. Children start from an environment scrubbed of ambient credentials and DSH_* values before explicit overrides merge.
  - Fully explicit spawn request (argv, cwd, stdio per stream, env overrides, grace, abort signal); no shell interpretation
  - Output modes: pipe (raw stream), inherit, or collect (bounded in-memory tail + optional spill file)
  - Offset-based non-consuming readers; done reports exit facts, waitForExit() proves managed-range quiescence
  - scrubbedParentEnv removes ambient credentials and inherited DSH_* names; explicit undefined tombstones remove an entry
  - spawnTerminal allocates a real PTY; one implementation registers per context and a second load fails
  - note: Service definition; callers own deadlines, teardown ladders, cause classification, and model-facing rendering.

**`@deepseek-ai/dsh-subprocess-local`** — Local host provider for ctx.subprocess: runs OS-owned managed ranges and real node-pty terminal sessions on the host machine, with explicit weaker fallbacks. It has no configuration — every disposition, limit, terminal size, and grace arrives on the spawn request from the calling capability seam.
  - Linux ordinary/terminal launches use transient user-systemd scopes; Windows ordinary launches use a helper-owned kill-on-close Job
  - Fallbacks (macOS, older/unavailable systemd, unavailable Windows native) use process-group, taskkill, or terminal-session observation with one warning
  - Collect mode keeps a bounded in-memory tail plus optional spill files (0700 dir, 0600 random-named files)
  - Children start from a scrubbed environment; disposal terminates and joins every selected range or session
  - No config fields; executable resolution verifies absolute paths and rejects relative paths containing separators
  - note: Host-exit finalization covers only JavaScript-observable exits; SIGKILL, OOM, and native crashes need an external supervisor.

**`@deepseek-ai/dsh-terminal`** — Persistent owner-scoped terminal sessions: the ctx.terminals service mints opaque session ids, routes session creation through registered backends, and fences every operation to the exact agent that created it. Backends own spawning and readiness; it defines no terminal mechanics itself.
  - Session state (shell/REPL) survives across tool calls; opaque session ids
  - Owner fencing: an operation naming another agent's session is rejected (FOREIGN_SESSION)
  - Stable error codes: NO_BACKEND, NO_SESSION, FOREIGN_SESSION, SEND_ACTIVE, OWNER_NOT_LIVE
  - Exactly one active send per session; a second send fails until the first settles
  - Process-local sessions — they do not survive a harness restart
  - note: Service only; pair with a backend such as dsh-terminal-bash and a tool package such as dsh-tool-terminal.

**`@deepseek-ai/dsh-terminal-bash`** — Shipped shell backend for persistent terminal sessions: starts a persistent interactive shell under the deployment's sandbox policy, detects readiness for input, and retains bounded line-oriented output. It provides the shell backend type and supports bash on POSIX and pwsh on Windows via a shellDialect setting.
  - Provides the shell type on ctx.terminals; shellDialect selects bash or pwsh
  - Readiness tiers: exact stdin-wait (Linux only), verified private prompt marker, output silence (inferred_idle), absolute timeout
  - Sandbox-mode fence: a mode downgrade is rejected while the owner still has open sessions or a spawn in progress
  - Line sanitizer + headless xterm; line-oriented output only, full-screen apps unsupported
  - Composes with local or remote execution worlds through the mounted subprocess provider
  - config: `backendType`=shell, `shellDialect`=bash, `shellPath / shellArgs`=per dialect, `maxReadBytes`=262144, `timeoutMs`=30000, `disposeGraceMs`=3000
  - note: Requires the terminal service, a subprocess provider, and the sandbox and policy services; confined modes need a same-world ctx.sandbox provider or the spawn fails before the shell starts.

**`@deepseek-ai/dsh-spill`** — Spill storage service: the ctx.spillStore.saveText() API saves oversized text and returns an opaque locator, exact byte count, and retrieval guidance, keeping full results retrievable without filling model context. It is a contract only — a backend must be mounted to store anything; the API offers no retention, replacement, retrieval, or search operations.
  - Single method saveText(owner, source, suggestedName, content) -> SpillRef { locator, bytes, retrievalHint }
  - Consumers render the locator with its retrieval hint and never parse the locator itself
  - Storage grouped by owning session; forked sessions inherit existing locators from the seeded log
  - suggestedName is only a hint — backends sanitize it to one safe segment and never trust it as a path
  - saveText rejects on a real storage failure; the caller owns degradation
  - note: Contract/implementation/policy split: dsh-spill defines it, dsh-spill-local implements it, dsh-spill-policy decides when.

**`@deepseek-ai/dsh-spill-local`** — Local filesystem spill backend: saves a caller's oversized text to a private session-scoped file on the host filesystem and returns that file's path as the locator, with retrieval guidance telling the model to read or grep it. Files are private to the current user, names are unpredictable, and each session's files group under a stable directory.
  - Private 0700 root, session-hash directory, random-prefixed leaf; exclusive owner-only write (open wx 0600)
  - suggestedName sanitized by an injective encodeSegment so separators, ../, NUL, and absolute paths cannot escape one segment
  - One-shot startup cleanup deletes files older than cleanupPeriodDays and prunes empty session directories
  - Never follows or deletes symlinks; POSIX ownership and sticky-dir safeguards
  - locator is the file path; retrievalHint is read with offset/limit or grep
  - config: `root`=private 0700 temp dir, `cleanupPeriodDays`=30
  - note: A long-lived deployment is not swept again until restart.

**`@deepseek-ai/dsh-spill-policy`** — Tool-result spill policy: replaces oversized plain-text tool results with a bounded head/tail preview plus a locator within maxInlineBytes, keeping the full text retrievable through the configured spill backend. Spill failures leave the original result visible, and omitting maxInlineBytes disables the policy.
  - maxInlineBytes caps model-facing plain-text results; omitted disables the policy entirely
  - Replacement never exceeds the budget (notice byte cost reserved first); if even the notice cannot fit, the original stays inline
  - Only final accepted plain-text results are shaped; read, mixed-content, nested, and blocked pass through unchanged
  - Same cap bounds the durable run_code sub-call log copy without changing the value returned to the program
  - Best-effort failure: missing owner/backend or a saveText rejection logs a warning and returns the original
  - config: `maxInlineBytes`=omitted
  - note: Text recognition cannot authenticate output: hasSpillNotice identifies a text convention, not proof the policy saved a result.

**`@deepseek-ai/dsh-win32-process`** — Low-level Win32 process primitives library (Koffi bindings): restricted-token creation, piped and inherited-stdio Job spawn, the ordinary Job runner, and settlement operations. It is consumed by the Windows ACL sandbox and the ordinary subprocess Job runner and is not a Cordis service.
  - One reusable ABI owner: abi.ts constants/layouts plus ffi.ts lazy kernel32/advapi32 loading
  - spawnPipedProcess: anonymous stdin/stdout/stderr pipes with partial-failure handle cleanup
  - spawnInheritedJobProcess: kill-on-close Job, suspended create, assign, resume — target code cannot run before Job assignment
  - spawnCurrentTokenJobProcess: uv_get_osfhandle mapping, sorted UTF-16LE env block, CreateProcessW
  - pollProcessExit / isJobEmpty / waitForProcessExit / drainPipe settlement primitives
  - note: Internal library, not a Cordis service; consumers own policy, async scheduling, output limits, cancellation, and final handle closure. Windows-only native loading.

**`@deepseek-ai/dsh-code-runtime`** — Abstract code-execution seam (ctx.codeRuntime): runs one model-written program against host-provided async binding functions through a configured backend. A request returns a lossless-JSON value, ordered per-channel logs, or a structured error; program failures resolve in the result while rejected promises indicate caller misuse.
  - run(request) executes a program as the body of an async function; top-level await and return work
  - Program failures resolve as result.error with an orthogonal kind (exception/timeout/abort/worker-exit/invalid-output/output-limit); rejection = seam misuse
  - Bindings are global objects of async functions (PTC mode passes one tools object)
  - Portable identifier rules and exclusion sets so one bindings list is valid across backends
  - Each run is isolated from prior runs; the runtime has no knowledge of tools or sessions
  - note: Service definition; backends subclass CodeRuntime and register as ctx.codeRuntime. PTC mode in dsh-tools is the consumer.

**`@deepseek-ai/dsh-code-runtime-worker-thread`** — Worker-thread TypeScript backend for ctx.codeRuntime: runs each model-written TypeScript program in a fresh Node worker with configurable compute, wall-clock, heap, and output limits, returning the completion value, ordered logs, or a structured failure. It provides containment, not a security boundary — model code has bash-equivalent trust.
  - Fresh worker per run; no state crosses runs and the program's world dies with its worker
  - Budgets: computeMs (busy time), maxWallMs (wall-clock), maxOutputBytes (serialized outer output), maxOldGenerationSizeMb (heap)
  - Type-stripped host-side and run as an async body; binding calls cross the message port as lossless JSON
  - Hostile-peer port: every inbound message is shape-validated and rebuilt; worker namespaces are null-prototype
  - Failures resolve as result.error; output-limit retains a fitting captured log prefix
  - config: `computeMs`=60,000, `maxWallMs`=600,000, `maxOutputBytes`=67,108,864, `maxOldGenerationSizeMb`=512
  - note: The shipped backend; a container-class backend providing a hard multi-tenant boundary is not implemented.


### LLM, web, hooks, MCP — 18 plugins

**`@deepseek-ai/dsh-llm`** — Provider-neutral model-call service (ctx.llm) that streams model requests through registered provider adapters. It exposes token-level streaming via ctx.llm.stream(), model discovery, capability resolution, and call-config validation, with one terminal finish chunk and provider-neutral failure codes.
  - ctx.llm.stream() yields token-level chunks ending in exactly one terminal finish chunk (success/error/aborted)
  - Registers provider adapters (dsh-llm-deepseek, dsh-llm-pi-ai) and configurable-provider routes for settings-driven activation
  - Resolves model metadata: context window, output default, reasoning efforts, input modalities, systemPromptUpdate mode
  - Deep-freezes requests before dispatch; every dispatched request is reconstructable from the session log
  - Owns no retry/rate-limit logic - retrying is delegated to dsh-llm-retry
  - note: The only supported path into provider adapters; mount it with at least one adapter. The service itself has no configuration.

**`@deepseek-ai/dsh-llm-deepseek`** — DeepSeek chat-completions adapter registering the single deepseek-official route. It streams DeepSeek models through the harness LLM service with configurable thinking/reasoning effort, image input via the Files API (inline base64 fallback), and an advisory model catalog; endpoint and credentials resolve per request.
  - Registers the deepseek-official route; the model id passes through to the wire, so new models need no re-registration
  - Configurable thinking/reasoningEffort (off|low|high|max) and a per-request output cap
  - Image input via the DeepSeek Files API with deterministic request projection, pixel/byte budgets, inline fallback, and quota cleanup
  - Per-request credential and endpoint resolution, so settings changes apply to the next request without restart
  - Stable failure codes: AUTH, QUOTA, RATE_LIMIT, CONTEXT_WINDOW_EXCEEDED, TRANSPORT, TIMEOUT, etc.
  - config: `apiKeyEnv`=DEEPSEEK_API_KEY, `baseURL`=https://api.deepseek.com, `thinking`=enabled, `reasoningEffort`=high, `maxTokens`=256000, `defaultContextWindow`=1000000
  - note: Can run beside dsh-llm-pi-ai because route names do not collide; registering another adapter for deepseek-official fails with DUPLICATE_ADAPTER.

**`@deepseek-ai/dsh-llm-pi-ai`** — pi-ai-backed multi-provider adapter routing model requests to multiple pi-ai providers, OpenAI-compatible gateways, or self-hosted servers from one providers dictionary. Per-profile model catalogs, reasoning efforts, and wire-compatibility switches; credentials resolve per request and supported providers support OAuth/interactive-key sign-in.
  - providers dictionary maps each route name to a profile; it may start with zero routes and activate when user settings add them
  - Installed pi-ai provider catalogs supply defaults; hand-declared routes declare api/baseURL/models without code changes
  - Per-profile retryPolicy, reasoningEfforts, modelOverrides, and compat wire-compatibility switches
  - OAuth or interactive-key sign-in through the harness authorization seam, stored and refreshed in the credential store
  - Endpoint model discovery for routes the installed catalog does not describe
  - config: `apiKeyEnv`=absent, `displayName`=provider name, `api`=catalog protocol, `baseURL`=catalog endpoint, `models`=installed catalog, `modelOverrides`=none
  - note: Each key of providers is the route name a request selects with GenerateOptions.provider.

**`@deepseek-ai/dsh-llm-retry`** — Retry executor that re-runs failed model requests at durable agent-step boundaries. Provider retryPolicy settings choose bounded normal-mode or unlimited always-mode retries; scheduled attempts reach the session log before backoff and retries run in the same open turn.
  - Listens on the agent/request-error waterfall and re-runs the failed step in the same open turn over durable history
  - Normal mode: finite budget, eligible failure codes, bounded exponential backoff (500ms to 10s, 10% jitter); always mode retries until success, cancellation, or disposal
  - Honors a valid provider Retry-After when it fits the policy bounds
  - Emits durable llm/retry and llm/retry-started session events
  - No configuration of its own and no model-visible retry/error text
  - note: A function plugin with no config; the retry policy lives on each provider adapter (route-level or per-profile). Direct ctx.llm.stream() consumers stay single-attempt.

**`@deepseek-ai/dsh-deepseek-llm-api-extensions`** — Registry for additive top-level fields on official DeepSeek LLM API requests. Contributor plugins claim one declaration-merged field, and dsh-llm-deepseek prepares the current contributions after serializing its base request; the fields stay outside model input.
  - register(field, provider) reserves one field per fiber; duplicate or malformed names fail synchronously
  - prepare(request) snapshots and prepares providers concurrently before HTTP dispatch
  - accept() runs captured post-2xx callbacks once; several failures become one AggregateError
  - dsh-session-log-deepseek owns dsh_session_log; dsh-plugin-package-inventory-deepseek owns dsh_plugin_packages
  - note: Official DeepSeek requests only; the provider-neutral LLM seam and llm-pi-ai do not consume this registry.

**`@deepseek-ai/dsh-web`** — Web access service (ctx.web) giving plugin and tool authors provider-neutral web search and URL fetch through interchangeable backends. It selects a usable backend per call, provides a stable WebError vocabulary, and enforces result limits; it makes no network requests on its own.
  - ctx.web.search() and ctx.web.fetch(), both accepting an optional AbortSignal
  - Execution-time provider selection: configured id wins, otherwise the single usable provider; ambiguity or absence throws a structured WebError
  - Enforces request.maxResults by truncating sources[] and setting truncated
  - A non-2xx fetch response is a result, not an error
  - config: `searchProvider`=unset, `fetchProvider`=unset
  - note: The shipped dsh-tool-web tools load this service for you; without at least one usable provider every call fails with a structured WebError.

**`@deepseek-ai/dsh-web-fetch-http`** — Anonymous public HTTP(S) fetch backend for ctx.web, registered as the http fetch provider. It provides bounded, safe URL retrieval with URL validation, public-address enforcement, connection pinning, same-origin redirects, byte/character caps, and an explicit product User-Agent; non-2xx responses are returned as results.
  - Accepts only http:/https: URLs without embedded credentials and rejects URLs over 2048 characters
  - Rejects non-public IPv4/IPv6 addresses (DNS64-aware) and pins the connection to the validated answer set
  - Same-origin redirects only; a cross-origin redirect fails and requires a fresh call
  - Classifies Content-Type, decodes the declared charset, and enforces byte and character caps
  - Machine-routable WebError codes: WEB_INVALID_URL, WEB_FETCH_TOO_LARGE, WEB_REDIRECT_BLOCKED, etc.
  - config: `maxResponseBytes`=5000000, `maxBodyChars`=100000, `timeoutMs`=30000, `maxRedirects`=5, `userAgent`=deepseek-harness/...
  - note: Only textual content decodes; a missing Content-Type or a binary type throws WEB_UNSUPPORTED_CONTENT_TYPE.

**`@deepseek-ai/dsh-web-search-deepseek`** — DeepSeek-backed search provider for ctx.web, registered as the deepseek-official search provider. It runs native DeepSeek web search through the Anthropic-compatible Messages API using the existing DEEPSEEK_API_KEY and returns structured search blocks as citeable sources.
  - Uses the Anthropic-compatible base (api.deepseek.com/anthropic/v1), distinct from the chat-completions base the LLM adapter uses
  - Parses web_search_tool_result blocks into sources (url, title, publishedAt, cited-text snippets); it never scrapes provider prose
  - One search costs a full Messages model turn in latency and generated tokens, with up to maxUses server-side searches
  - Per-search credential resolution; a missing credential fails as WEB_PROVIDER_CREDENTIAL_MISSING
  - config: `apiKey`=omitted, `apiKeyEnv`=DEEPSEEK_API_KEY, `baseURL`=https://api.deepseek.com/anthropic/v1, `model`=deepseek-v4-flash, `apiVersion`=2023-06-01, `maxTokens`=4096
  - note: Heavier per-search cost than a dedicated retrieval endpoint; never reuse $DEEPSEEK_BASE_URL, which points at chat completions.

**`@deepseek-ai/dsh-web-app`** — Browser GUI bundle for dsh (run via dsh --profile web): interactive chat, model and settings management, and session history, using the same model access, tools, and safety defaults as other surfaces. Startup prints an authenticated URL and normally opens it in the default browser.
  - One patch plus one runtime glue plugin over the shared dsh-base core
  - Per-session agent composition from shipped presets (standard by default) instead of a process-wide tool set
  - Browser-trust fence built from sampled LAN addresses plus --trusted-host; loopback only by default
  - Prints a dsh web: URL line with a fresh process token and hands off to the default browser; SSH sessions keep the URL but skip the handoff
  - surfaceContext gives the agent GUI-orientation context and exposes DSH_WEB_URL to its shell commands
  - config: `openBrowser`=true, `printUrl`=true, `surfaceContext`=true, `trustedHosts`=[]
  - note: The frontend must be built; binding all network interfaces (--host 0.0.0.0) is rejected for safety.

**`@deepseek-ai/dsh-web-frontend`** — Web application entry: a Vite build over the @deepseek-ai/dsh-client-web shell library; the built dist/ is what dsh web (apps/cli) serves.
  - No README; capability taken from the package.json description
  - Vite build of the browser shell, with build / dev / watch scripts and a preview build packing a VFS image
  - dist/ is the served artifact; the CLI serves it for the dsh web surface
  - note: A build-artifact package, not a runtime plugin; it exposes no configuration table.

**`@deepseek-ai/dsh-webhook`** — Host webhook rule runtime (ctx.webhookRuntime) that turns trusted external events into new Workspace Sessions. A rule registers a branded id, a provider kind, and a run(delivery, signal) callback returning null or one WebhookSessionRequest; the built-in action creates an ordinary root Session in a Web Workspace.
  - register(rule) / dispatch(delivery) interface; provider authentication belongs to adapter packages
  - WebhookSessionRequest requires workspacePath, title, prompt, agentPreset, and permissionPreset; an optional model names an explicit route
  - Validates presets, resolves or creates the canonical Workspace, mounts the preset, then applies permissions/title/prompt; Agent.followup() is the commit point
  - Registration is an effect whose disposer hides the rule then aborts and drains active callbacks
  - note: Process-local fire-and-forget: no queue, replay, dedup, or completion result; callbacks are arbitrary trusted code that must cooperate with cancellation.

**`@deepseek-ai/dsh-webhook-github`** — Signed GitHub webhook adapter registering one exact HTTP route on the injected ctx.webServer. It bounds and verifies GitHub's raw JSON body (HMAC via X-Hub-Signature-256), projects a provider-neutral delivery, calls ctx.webhookRuntime.dispatch(), and returns 202 without waiting for rules or Sessions.
  - Only POST application/json; requires X-Hub-Signature-256, X-GitHub-Delivery, and X-GitHub-Event
  - HMAC verified before JSON parsing; the secret is resolved per request so rotation applies without reloading
  - Returns 202 on verified dispatch, with 400/401/405/413/415/503 for other outcomes
  - Never logs the secret, signature, or payload
  - config: `source`=required, `path`=required, `secretEnv`=required, `maxBodyBytes`=required
  - note: No TLS - normally loopback-only behind a TLS reverse proxy; GitHub event-specific field validation belongs to each rule.

**`@deepseek-ai/dsh-http-proxy`** — Outbound HTTP proxy support: one policy resolved from the launch environment reaches every request that Node's built-in fetch would otherwise send direct (LLM, web-search, and HTTP MCP traffic). It is a library rather than a plugin - the dsh launcher resolves and installs the policy before plugins load, so nothing needs mounting.
  - Reads http_proxy/https_proxy/no_proxy/all_proxy (lowercase first, uppercase fallback); ALL_PROXY backs both schemes and HTTPS falls back to the HTTP proxy
  - Loopback is always bypassed; NO_PROXY entries match subdomains, ports, '*' and IPv6 literals
  - Public helpers: proxyRouteFor(), proxyEnvironmentForChild(), and clearedProxyEnv()
  - Unsupported proxy URLs (SOCKS/PAC) are reported and that scheme connects direct rather than stopping startup
  - note: Process-wide, so it applies to all outbound fetch including LLM/MCP traffic; dsh-web-fetch-http is deliberately proxy-exempt, and code-runtime/workflow workers receive no proxy.

**`@deepseek-ai/dsh-hook-protocol`** — Shared hook rules library behind the Claude Code and Codex bridges, defining what a hook can do and what happens when it runs. It is never installed directly - mounting dsh-hooks-claude-code or dsh-hooks-codex applies these rules to an existing hooks.json.
  - Command hooks can block an action with a message (exit code 2), ask before a tool runs, attach extra context, or request the run stop
  - Any exit other than 2 is a non-blocking failure; an unreadable config logs a warning and no hooks run
  - Merging applies deny > ask > allow precedence and keeps the first continue:false stop sticky
  - Emits log-only hook/invoked and hook/result session events that must sit inside an open turn
  - note: Only command hooks run; http, mcp_tool, prompt, and agent handlers are skipped with a warning.

**`@deepseek-ai/dsh-hooks-claude-code`** — Runs command hooks from an existing Claude Code hooks.json or settings config during agent runs, without a rewrite. Supported events (SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop, SubagentStart, SubagentStop) can block prompts or tool calls with model-visible reasons, attach conversation context, or force another model turn.
  - One configPath is read once at process start; ${CLAUDE_PLUGIN_ROOT} and ${CLAUDE_PROJECT_DIR} are substituted and CLAUDE_PROJECT_DIR is set
  - SubagentStart attaches context to a live in-process subagent; SubagentStop observes only
  - Hooks run serially in config order; the most-restrictive fold is order-independent
  - 23 of Claude Code's current 30 hook events are unsupported, and many supported events are partial
  - config: `configPath`=required, `pluginRoot`=-, `projectDir`=session workspace, `defaultTimeoutMs`=600000, `stderrSummaryMaxChars`=500
  - note: A compatibility adapter for the command-hook subset; bespoke behavior belongs in a native plugin on the same extension points.

**`@deepseek-ai/dsh-hooks-codex`** — Runs command hooks from an existing Codex hooks.json during agent runs. It supports five Codex hook points (SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop) to block prompts or tool calls, attach context, or force another agent step; payloads are Codex-shaped (snake_case, turn_id, model).
  - Five supported events; 5 of Codex's current 10 events are unsupported (PermissionRequest, PreCompact, PostCompact, SubagentStart, SubagentStop)
  - Codex matchers are always unanchored regexes; hooks run serially in config order
  - Only synchronous command hooks run; an async or non-command hook is skipped with a warning
  - No pre-tool approval or input-rewrite path - dialect-shaped rather than maximal
  - config: `configPath`=required, `model`='', `defaultTimeoutMs`=600000, `stderrSummaryMaxChars`=500
  - note: One process-level configPath is parsed at load; no layered config discovery or live reload.

**`@deepseek-ai/dsh-mcp-client`** — MCP client bridge letting the model call tools from external Model Context Protocol servers as native harness tools. One config entry per server (stdio or Streamable HTTP); tools appear as mcp__<serverName>__<toolName> with atomic tool-set syncs and automatic reconnection.
  - Server-qualified stable naming: mcp__<serverName>__<rawName>, matching the Claude Code and Codex naming shape
  - stdio (with scrubbed ambient env) and streamable-http transports, plus a per-call toolCallTimeoutMs
  - Automatic reconnect with exponential backoff (500ms to 30s, 10 attempts) that refreshes the tool set
  - Full-generation-or-none syncs: a fetch failure keeps the previous generation, and a registration conflict rolls back the attempted generation
  - Images are bridged when supported; MCP resources and prompts are unsupported
  - config: `transport`=required, `serverName`=required, `command / args / env / cwd`=-, `url / headers`=-, `toolCallTimeoutMs`=60000, `failOnStartupError`=false
  - note: No server is enabled by default. Tool definitions add tokens to every model request; a slow or crashed server can delay startup.

**`@deepseek-ai/dsh-plugin-package-inventory-deepseek`** — Active Loader plugin package inventory for official DeepSeek LLM API requests. It injects the Loader, the live Agent registry, and ctx.deepseekLlmApiExtensions, then owns the version-1 dsh_plugin_packages field containing {name, version} pairs of active non-group Loader entries.
  - Owns the dsh_plugin_packages request extension; enabled by default in shipped profiles
  - Re-reads active non-group Loader entries per request; a standing agent-preset Loader tree joins the same collection
  - Only fibers whose root is ACTIVE and whose Loader state is enabled are included; disabled, pending, failed, disposed, and loose modules are excluded
  - Exact name/version pairs are deduplicated and sorted with a locale-independent comparison
  - config: `enabled`=true
  - note: Provider metadata outside model input - it adds only HTTP request bytes; in-place package replacement requires a restart.


### Storage, settings, credentials — 22 plugins

**`@deepseek-ai/dsh-storage`** — Storage hub (ctx.storage) that mounts named storage backends and data-form facilities side by side, so host packages can keep typed application data durable without putting it in session history. It is a pure registration table (name → backend, form → facility) that performs no IO itself; backends are resolved by name and forms as ctx.storage.<form>, with the domain form also served as ctx.storageDomain.
  - Multiple backends stay mounted side by side; which serves a domain is consumer config, not a hub-wide choice
  - Fails loud with stable StorageError codes (backend-not-found, form-not-mounted, duplicate-backend/duplicate-mount)
  - Host-side only, no tools/prompts/session events; zero direct tokens
  - Published lifecycle-only keys (storage.backend.<name>) so the domain form activates only after its backends register
  - note: Must be mounted together with a backend and a data-form package; the agent loop never needs it.

**`@deepseek-ai/dsh-storage-domain`** — Domain data form (ctx.storageDomain) that declares schema-validated key-value domains (name, version, zod record schemas) and opens them over a configured storage backend. Reads return synchronously from validated in-memory state while each write becomes durable before it resolves and emits domain/changed in order, so product packages use domain handles instead of touching backends directly.
  - defineDomain/domainTable declare a domain once; validation fails loud at module load
  - One per-domain write chain serializes put/delete/update/global.set; a rejected backend write leaves memory untouched
  - Emits ordered domain/changed events after the commit point; throwing listeners are contained
  - DomainError codes: already-open, facet-unsupported, invalid-record, missing-key, closed; backend version-mismatch passes through
  - No migration: a stored version differing from the spec rejects at open
  - config: `backend`=required, `routes`={}
  - note: Consumers own the handle lifecycle via domain.close(); the facility closes any domain left open on unmount.

**`@deepseek-ai/dsh-storage-json`** — JSON storage backend registered as backend `json`, storing domain data as readable JSON under a configured root. Its default `single` layout keeps one complete <unit>.json per unit; its `per-record` layout keeps one version-stamped document per record; both publish each changed file atomically while the domain layer orders calls.
  - Readable, editable JSON; created root is 0o700 on demand
  - single layout: memory-authoritative, rewrites and atomically replaces the whole unit file
  - per-record layout: directory-authoritative, one <unit>/<table>/<key>.json per record with optional global.json
  - Atomic publication via temp write, fsync, rename, parent-dir fsync (POSIX)
  - Record keys must match [a-zA-Z0-9_-]+; unsafe keys reject before any file operation
  - config: `root`=required
  - note: single rewrites the whole unit per write — route high-volume domains to the SQLite backend instead; no cross-process write locking.

**`@deepseek-ai/dsh-settings`** — User-settings service (ctx.settings) that lets users change a plugin's configuration at runtime without restarting or re-reading cordis.yml. Each namespace combines schema defaults, a composition `base` layer, and user overrides; readers receive a deep-frozen resolved snapshot, and writes touch only the user layer, are serialized per namespace, and may reject stale revisions instead of overwriting newer changes.
  - register(ns, schema, { base }) then get()/update()/replace()/mutate() against a layered resolved value
  - update deep-merges into the user section; replace({}) resets to base and defaults; mutate applies ordered set/unset path edits
  - watch(callback) invokes observers in commit order; failures are contained and logged
  - describe()/redactSecrets expose configuration surfaces; secrets are stripped to { path, set } slots
  - settings/updated and settings/document-updated events; writes reject non-JSON-compatible data and accept expectedRevision conflict checks
  - note: Stores nothing by itself; mount a provider such as dsh-settings-file. Limited to a single user layer; redactSecrets is not yet a proven wire boundary.

**`@deepseek-ai/dsh-settings-file`** — File-backed settings provider that keeps every namespace's user settings in one YAML or JSON document (default settings.yaml under the harness home), so users can edit it directly and changes take effect live, or write through the service. YAML writes preserve comments, anchors, and formatting on untouched nodes, and a section owned by an unloaded plugin is never dropped.
  - Hot-reloads external edits via a debounced watcher; deleting the file resets namespaces to defaults and base
  - Boot fails loud on an invalid document; a live reload that fails warns and keeps the last good sections
  - Every write is a read-modify-write under a cross-process writer lock (2s acquisition deadline, exponential backoff)
  - YAML edits are leaf-level diffs preserving comments/anchors/formatting; JSON re-serializes without comments
  - Document created 0600 under an owner-only 0700 directory; replaced atomically via a random-suffix temp sibling
  - config: `path`=<harness home>/settings.yaml, `dshHome`=$DSH_HOME or ~/.dsh, `watch`=true, `debounceMs`=100
  - note: Same-namespace concurrent writes stay last-write-wins; a missed watcher event stays unseen until the next signal.

**`@deepseek-ai/dsh-credentials`** — Credential seam (ctx.credentials) that keeps secret values out of configuration by letting settings and cordis.yml refer to key names, and also stores durable per-plugin credential records (authorization grants, provider environment values). A rotated stored key applies to the next request without a restart or config edit, and configuration UIs can report whether a key or record is set, its source, and writability without exposing values.
  - credentialRef / credentialKey branded identifiers; resolve/describe/set/unset for references and readRecord/describeRecord/listRecords/modifyRecord/deleteRecord for records
  - Configuration carries references, never secrets; describe() never returns the value
  - An empty stored value counts as absent; an empty record remains a deliberate stored credential
  - modifyRecord is the only record write path, running read-decide-replace under exclusive access (cross-process where supported)
  - credentials/reference-updated and credentials/record-updated events; listener failures are contained
  - note: References have no enumeration and are environment-variable-shaped (flat POSIX namespace); a key supplied by the launch environment is read-only and cannot be overwritten.

**`@deepseek-ai/dsh-credentials-local`** — File-backed credentials provider that keeps API keys and other secrets in a private versioned YAML document under the harness home, with automatic reload and persistence across restarts. Lookup follows a fixed precedence: launch environment, then stored file, then project .env, then harness-home .env, so a newly saved value immediately overrides older .env values.
  - Versioned document with refs and records sections; only the owner interprets a grant payload
  - Precedence: launch env (read-only) > stored file (writable) > project .env > home .env
  - File created owner-only; POSIX refuses to load a file any other user can read (chmod 600 guidance)
  - Writes patch under a cross-process writer lock; reloads swap the snapshot wholesale
  - Boot/reload reject unreadable, invalid, or too-widely-readable documents; a failed reload keeps the last good snapshot
  - config: `path`=<harness home>/.credentials.yaml, `dshHome`=$DSH_HOME or ~/.dsh, `watch`=true, `debounceMs`=100
  - note: Cannot isolate secrets from the agent: tool processes run as the same OS user. Same-reference concurrent writes are last-write-wins; atomic, not crash-durable.

**`@deepseek-ai/dsh-anonymous-user-id`** — Provides one anonymous identifier per harness home to correlate telemetry, feedback, and DeepSeek provider requests from the same installation without identifying the user. The random UUID is stored in $DSH_HOME/.anonymous-user-id, persists across restarts, and is regenerated after deletion; built-in features create and attach it automatically.
  - getOrCreateAnonymousUserId() is stable for the process lifetime and matches what built-in features use
  - Minted from crypto.randomUUID(); never derived from hostname, network address, or git remote
  - Synchronous, memoized per resolved path; best-effort persistence so an unwritable home still yields a usable id
  - Carried as telemetry user.id, in feedback acknowledgements, and on the x-deepseek-harness-user-id provider header
  - note: Library, not a plugin; no Cordis entry or config. Deleting the file mints a new identity and does not reset the current process.

**`@deepseek-ai/dsh-atomic-write`** — Zero-dependency filesystem primitive for replacing a file without exposing partial content or following a symlinked temporary path, plus a cross-process writer lock that serializes read-modify-write cycles. Each replacement uses caller-selected permission bits on a fresh inode, which safely narrows an existing file's permissions.
  - writeFileAtomic writes a random-suffix sibling with exclusive create, then renames it over the target
  - withFileLock creates a <filename>.lock sibling; only writers contend, contenders back off exponentially and time out
  - Fresh inode carries the caller-stated mode through the rename, avoiding a chmod race; readers never take the lock
  - Windows replacement interference (EACCES/EBUSY/EPERM) is retried with bounded backoff; failures leave the target untouched
  - A contender never deletes an existing lock; orphan lock recovery is an operator action
  - note: Atomic, not crash-durable — it does not fsync the file or directory. String content only; the lock's parent directory must already exist.

**`@deepseek-ai/dsh-file-reference`** — Host-backed UI seam for @file mention completion: a UI asks for path candidates for the addressed agent, the model types @path or @"path with spaces", and picking a candidate inserts the matching mention as ordinary prompt text. The seam owns no filesystem access — a concrete provider supplies candidates, ranking, caching, and invalidation.
  - ctx.fileReferences.list(agent, query, signal) returns path-only file/directory candidates, deterministically ranked by the provider
  - Grammar: an @ at input start or after whitespace triggers completion; @"..." opens a quoted mention and directory candidates keep the quote open
  - Selecting a candidate never reads or attaches file contents; the model must call a filesystem tool to inspect a file
  - Session Controller exposes the same discovery to browser consumers via the fileReferences/list Remote
  - note: Mounting the seam without a provider gives an empty completion surface. Path candidates are advisory — align the provider with the effective read tool.

**`@deepseek-ai/dsh-file-reference-local`** — Local-workspace @file completion provider that ranks paths from each agent's local workspace (session working directory, falling back to the host process directory) with bounded discovery that stays responsive in large repositories. Results refresh after tool activity without blocking completion, and directory symlinks are never followed; when `read` is available the model also receives stable guidance for interpreting referenced paths.
  - Typing @ returns up to maxResults ranked path candidates; a /-containing query lists a directory's entries directly
  - Bounded recursive index with fuzzy ranking (exact, prefix, substring, subsequence, directory bonuses)
  - tool/result events mark the agent's index stale; the next bare query answers from it while a replacement builds in the background
  - Installs the stable FILE_REFERENCE_PROMPT section while the addressed agent has a read tool
  - Directory candidates keep the mention open with a trailing slash; excluded and unreadable subtrees contribute no candidates
  - config: `maxResults`=20, `maxEntries`=50000, `excludedDirectories`=['.git','node_modules','dist','build','out','coverage','target','.next','.nuxt','.turbo','.venv','__pycache__','.pytest_cache','.mypy_cache','.gradle']
  - note: Host-local namespace only (matches the Harness host read tool); no .gitignore semantics; lib is deliberately not excluded by default.

**`@deepseek-ai/dsh-attachment`** — Durable image and file attachment capability (ctx.attachments) for prompts and commands, reusable after restarting the same session. Images are validated and normalized to a provider-independent 8-bit sRGB/sRGBA raster (PNG, JPEG, WebP, GIF within deployment limits); other files are stored byte-for-byte without format or size limits and models read them on demand through saved read-only paths rather than receiving their bytes.
  - Admit prompt content or encoded files; images normalized and persisted before the batch publishes, refusing the whole message on any failure
  - Images reused across session history and projected into deterministic route-sized request versions; bytes verified on read
  - Generic files record name, size, and digest, and give the model one line naming the saved path to read only when needed
  - Stable AttachmentError codes with a recognizable admission subset so protocol adapters map their own vocabulary
  - Save as bytes or bounded stream with backpressure/cancellation; content-addressed deduplication of identical bytes
  - note: Attachments are never deleted automatically; audio/video have no dedicated handling; unsent composer drafts are not saved.

**`@deepseek-ai/dsh-attachment-local`** — Local storage backend that keeps image and generic-file attachments durably below DSH_HOME on the machine running DSH. Images are validated, normalized for model requests, and cached per route; generic files are preserved byte-for-byte with no admission limits; identical bytes are stored once and reads verify length and content.
  - Content-addressed objects at <DSH_HOME>/attachments/v1 with fsync-chain durability to a proven boundary
  - Normalize once, project per route: deterministic request variants with cache identity including attachment id, transform version, budgets
  - Alpha images use WebP, opaque use JPEG, on an 85/75/60 quality ladder; smallest retained when none meets the byte target
  - Generic files as read-only hard links so different names for equal bytes do not duplicate disk content; verified bounded reads
  - Limits are write-time policy, so tightening them later never makes admitted history unreadable
  - config: `dshHome`=resolved, `maxImageBytes`=20 MiB, `maxImagesPerMessage`=20, `maxMessageImageBytes`=200 MiB, `maxImagePixels`=64000000, `maxImageDimension`=8192
  - note: Images are kept forever and remain local to one machine; animated GIFs become static (first frame only); encoder output is versioned by the installed Sharp/libvips build.

**`@deepseek-ai/dsh-workspace`** — Workspace entity registry (ctx.workspaceRegistry) that keeps an ordered, persistent list of project directories and the sessions run in each, so hosts can build project sidebars, hide sessions from grouping without deleting histories, and remove projects without deleting folders, files, or sessions. It is invisible to models and adds no prompt or request-context cost, but requires session persistence and storage backends.
  - Create/rename/reorder projects from any existing fully qualified directory; canonicalized via fs.realpath
  - A session joins the project of its recorded directory (one project only); unvalidatable sessions stay ungrouped
  - Hide (archive) sessions from grouping without losing their history or place; removing a project never touches folder/files/sessions
  - Two-write mutations with a pendingMutation marker so startup completes an interrupted create/delete
  - Bootstrap builds projects from persisted session headers on first start; invariant checks the entity cache mirrors the durable table
  - note: Takes no configuration of its own; requires a session store, session persistence backend, and storage rows. Archiving is one-way; re-adding a directory starts a fresh project.

**`@deepseek-ai/dsh-home-paths`** — Shared resolution of the DeepSeek Harness data root and user-data paths for packages that need one consistent root, tilde expansion, and stable watch paths. An explicit path wins over $DSH_HOME, which wins over ~/.dsh; blank environment values are ignored, and helpers can render the root without revealing an absolute machine path.
  - resolveDshHome() and dshHomePath(child) give one resolved root and derived child paths
  - dshHomeDisplay renders the root symbolically (~/.dsh or $DSH_HOME), never leaking an absolute machine path
  - expandHomePath expands only bare/current-user tilde forms; named-user and other forms pass through unchanged
  - canonicalizeWatchPath resolves the deepest existing ancestor and restores the missing suffix so a target can be watched before it exists
  - note: Direct library dependency, not a cordis.yml plugin; blank or whitespace $DSH_HOME is treated as unset.

**`@deepseek-ai/dsh-brand`** — Nominal string and number types with stateless constructors that make structurally identical values non-interchangeable at the type level (e.g. a SessionId cannot be passed where a ToolCallId is expected). brandString and brandNumber apply nominal brands with no shared runtime state, so owning packages can define domain types without importing an unrelated capability.
  - brandString<T>() and brandNumber<T>() change only the static type and perform no runtime validation
  - Branded values compare, log, serialize to JSON, and cross the wire as ordinary strings/numbers
  - The private symbol never exists at runtime, so separate installed copies yield interchangeable values
  - Used for ToolCallId, SessionId, JobId, and SessionSeq vs SessionLogOffset; stays dependency-free so capabilities own their own meaning
  - note: Library, no Cordis entry or config; validate domain grammar before branding.

**`@deepseek-ai/dsh-chunked-list`** — Immutable append-only lists for projection state with bounded append copying, insertion-order iteration, and Zod checkpoint validation. Appending returns a new head without modifying existing nodes, so callers retain earlier list versions without copying the whole collection; the subagent catalog uses it for immutable projection state.
  - appendChunkedList(prev, value) returns a new head; an empty list is undefined
  - iterateChunkedList visits all N values in O(N) with O(N/64) scratch space, oldest to newest
  - Newest chunk holds up to 64 values, so appends copy at most one chunk (bounded O(1) work)
  - chunkedListSchema(valueSchema) validates JSON checkpoints and rejects unknown fields, invalid values, and empty/oversized chunks
  - note: Append-only — no removal or random access. Stored values are shared by reference and must be treated as immutable.

**`@deepseek-ai/dsh-deque`** — Circular deque for Host and browser packages that need amortized constant-time queue operations, immediate release of removed entries, and bounded vacant storage. Callers append or prepend entries and remove them from the front without moving every remaining entry after each removal, so long-lived in-process queues can be drained efficiently.
  - pushBack / pushFront / popFront with FIFO or optional front insertion; explicit clear
  - Circular array storage; geometric growth and quarter-full shrinking keep copying amortized constant time
  - Removing an entry clears its slot immediately, releasing the entry and bounding vacant storage
  - Consumer owns wake-up, failure, cancellation, capacity, and overload behavior
  - note: No capacity policy — the deque does not bound, coalesce, or reject entries; it does not impose a queue limit or translate consumer failures.

**`@deepseek-ai/dsh-util-crypto`** — Zero-dependency browser-safe UUID and byte-encoding helpers. UUID minting uses crypto.getRandomValues, the one random primitive every shipped context provides, so code that must run in a non-secure context (a LAN HTTP page or worker) can mint UUIDs without calling the secure-context-only crypto.randomUUID; the repository-wide no-restricted-properties lint rule points callers here.
  - randomUUID() returns a random RFC 9562 v4 UUID string, a drop-in for crypto.randomUUID()
  - bytesToBase64(data) produces canonical base64 for a byte array in bounded chunks
  - Uuid type matches crypto.randomUUID's declared five-group string shape
  - Library only: no ctx, no plugin, no state; Node-only node:crypto randomUUID callers stay as they are
  - note: v4 only (no other versions, namespaces, or parsing); uniqueness is probabilistic at 122 random bits.

**`@deepseek-ai/dsh-util-time`** — Zero-dependency IANA time-zone validation and canonicalization for wire boundaries that accept a caller-reported time zone. canonicalClientTimeZone admits UTC or an IANA Area/Location name and answers the platform-canonical spelling, so an alias never reaches a durable record where it would not compare equal later.
  - canonicalClientTimeZone(value) returns the canonical UTC or IANA Area/Location name, or undefined for blank/padded/abbreviated/single-segment/unsupported zones
  - Validation only — no formatting, offset arithmetic, DST reasoning, or instant conversion
  - Caller raises its own refusal (session/invalid-time-zone, subagent/invalid-time-zone)
  - note: Alias resolution follows the runtime's ICU data, so different Node builds may disagree; library only, no ctx or state.

**`@deepseek-ai/dsh-util-values`** — Runtime helpers for lossless JSON values, immutable object graphs, structural JSON equality, and exhaustive closed-union failures. Callers can validate untrusted values, detach a JSON snapshot, freeze a published value, compare JSON-compatible data, or terminate an unreachable branch without importing a capability package; the helpers hold no shared registry or mutable state.
  - isJsonValue / snapshotJsonValue accept only lossless JSON roots, rejecting cycles, sparse arrays, symbols, functions, and class instances
  - deepFreeze freezes an object graph in place, deliberately leaving live AbortSignal objects mutable
  - deepEqualJson compares JSON-compatible arrays and records structurally
  - assertNever(value, context?) in a closed union's default branch makes a new variant fail compilation and throws on an escaped runtime value
  - Validation uses an explicit work stack so deeply nested values do not consume the call stack
  - note: deepEqualJson assumes JSON-compatible inputs and is not a general object comparator.

**`@deepseek-ai/dsh-util-workspace-path`** — Browser-safe Workspace path helpers shared by Workspace-facing client and controller packages. It joins Workspace-relative paths, abbreviates POSIX home directories for display, derives Workspace titles from POSIX or Windows paths, splits a path into directories and final segment for display, and owns the dsh-resource://file/... address grammar that names a workspace file across the Sidebar and resource model.
  - dsh-resource://file/session/<sessionId>/<path> names the authorizing Session plus a workspace-relative or absolute path
  - fileAddressFor(sessionId, cwd, path) builds Session addresses, relativizing inside cwd; absoluteFileAddress builds the Session-less form
  - parseFileAddress decodes segments and returns { scope, sessionId, path } or undefined for unknown scope/scheme/escape
  - relativizeToCwd removes the workspace prefix for display while preserving paths outside it
  - Resolution is lexical and preserves the Workspace path's separator; home abbreviation is POSIX-only
  - note: Browser-safe, no Cordis service or runtime state; the Session-less absolute form carries no authorizing Session so the file provider cannot read it.


### SDK, ACP, API, cordis runtime — 17 plugins

**`@deepseek-ai/dsh-acp`** — Automation-only Agent Client Protocol (ACP v1) server over JSON-RPC stdio that lets trusted programs drive persistent DeepSeek Harness agents: create or resume sessions, choose model and reasoning effort, mount stdio/HTTP MCP servers, submit or cancel work, receive semantic updates, and close sessions. Intentionally exposes only the standard ACP surface, omitting DSH-specific presentation and interactive UI features.
  - One connection can multiplex several independent sessions, each with its own Agent handle, MCP mounts, and teardown
  - Persistence supports session/list, session/resume, and session/close across process restarts; deletion, fork, and transcript replay are unsupported
  - Supports session/prompt with text, resource links, and raster images; one prompt in flight per session with quiescent settlement
  - session/request_permission offers one-shot allow/reject choices a client can answer automatically
  - run via `pnpm dsh --profile acp`; `dsh-subagent-acp` is the matching out-of-process client
  - config: `provider`=None, `model`=None, `sessionListPageSize`=100
  - note: Explicitly the automation/out-of-process subagent path; trusted controllers only, no auth required.

**`@deepseek-ai/dsh-acp-app`** — The automation-only ACP stdio application as a `dsh --profile acp` profile bundle over dsh-base: it sets the coding-agent persona and a default model route, mounts an app-owned zero-option command provider, and starts the dsh-acp server only after that provider accepts the invocation, so `--help` writes help and exits without claiming stdin/stdout.
  - Binds stdin EOF to the launcher's bounded successful shutdown; stdout is reserved for newline-delimited ACP JSON-RPC frames
  - Disables model-generated session titles (ACP exposes no title surface) in favor of deterministic fallback titles
  - Ships rows creating sessions with deepseek-official / deepseek-v4-flash; a later patch can replace the row's config
  - Base profile owns adapters, tools, persistence, policy, settings, credentials, and the per-session workspace from the ACP client
  - note: Runnable composition for the ACP automation path; adds no private method, capability, _meta, env var, or transport field.

**`@deepseek-ai/dsh-sdk-app`** — The SDK stdio application as a `dsh --profile sdk` profile bundle over dsh-base: it sets the coding-agent persona, mounts an app-owned zero-option command provider, and starts the dsh-sdk-jsonrpc-server only after that provider accepts the invocation.
  - Stdout carries only newline-delimited JSON-RPC frames; stdin EOF and protocol shutdown drive bounded shutdown
  - Disables model-generated session titles and keeps deterministic fallback titles
  - Base file tool defaults are read, write, and edit; adding str_replace_editor needs an explicit insertion patch
  - DSH_MAX_TOKENS_AS_SUCCESS controls whether token-limited subagent completion is reported as success or error
  - config: `profile`=sdk
  - note: Runnable SDK JSON-RPC application; provider/model and workspace cwd arrive via the SDK initialization request.

**`@deepseek-ai/dsh-sdk-minimal`** — A standalone minimal SDK profile (`dsh --profile sdk-minimal`) that is a complete Cordis tree without the shared base bundle: it advertises only a platform-selected persistent shell (bash on Linux/macOS, pwsh on Windows), persists sessions as uncompressed JSONL, and takes its model from the SDK initialization request.
  - Single tool: one owner-scoped persistent shell with a 300-second timeout
  - Deliberately excludes dsh-base, Web, settings, credentials, telemetry, compaction, filesystem tools, workspace instructions, skills, jobs, and subagents
  - danger-full-access policy lets the shell modify any path the process can reach, so it requires an isolated workspace
  - DSH_SYSTEM_PROMPT replaces the default persona; DSH_CONTEXT_WINDOW supplies a fallback model capacity; DEEPSEEK_API_KEY provides the credential
  - note: Minimal cross-platform runtime; excludes subagents by design — choose `dsh --profile sdk` when product services are needed.

**`@deepseek-ai/dsh-sdk-jsonrpc-server`** — Serves the SDK wire protocol over stdio so out-of-process SDK clients can drive harness agents: it opens one session per sessionId, queues user prompts, and streams every session event and agent status transition back to the client. Mount it as the `jsonrpc` plugin in a Loader composition; the surrounding tree supplies agents, model adapters, persistence, and tools.
  - Creates one agent per sessionId on first use; a registered model adapter wins the route, with a deepseek-official fallback
  - initialize is the runtime-readiness boundary — it waits for the plugin tree to settle and returns the wire-stable identity deepseek-harness-sdk-runtime
  - Streams durable facts as session.event and whole-agent lifecycle transitions as session.status
  - Answers shutdown by disposing the root context and exiting 0; unloading only the plugin stops serving without exiting
  - config: `maxTokensAsSuccess`=false
  - note: Stdout must carry only JSON-RPC frames — a composed stdout logger would corrupt the channel.

**`@deepseek-ai/dsh-sdk-protocol`** — The SDK wire protocol library shared by both ends: one newline-delimited JSON-RPC 2.0 transport plus the named request, result, and notification types spoken between a Harness runtime and its SDK clients. A pure library with no plugin, configuration, or registrations.
  - One JSON-RPC 2.0 message per newline-terminated line over caller-owned byte streams; malformed lines are ignored
  - Three client-to-server requests: initialize, session/prompt, shutdown
  - Four server-to-client notifications: session.event, session.status, subagent.started, subagent.finished (in-process runs only)
  - HarnessSdkRequestMap / HarnessSdkNotificationMap index the shapes by method name; package root exports them with the transport
  - SessionPromptResult.messageId identifies the queued message, not a later assistant message or turn ending
  - note: No version negotiation (serverInfo.version 0.0.1, unvalidated) and no cancel or session-close methods; shapes are mirrored (not imported) by the Python SDK.

**`@deepseek-ai/dsh-api-gateway`** — A two-sided Typert RPC endpoint for Host and Client Cordis environments: the Host entry provides ctx.typertGateway.invoke()/stream(), and `@deepseek-ai/dsh-api-gateway/client` provides ctx.remote — both consume the same generated InvocationDescriptor contract, with Connection carrying unary correlation/trust/envelopes and Gateway owning multiplexed Remote streams.
  - Host invoke() resolves the current descriptor and Cordis Service, validates exact named args, and validates results; strict mode reads generated descriptors from ctx.typert.local
  - Client ctx.remote.$mount() installs generated namespaces; unary calls return RemoteResult<T> that never rejects for a carrier problem
  - Cancellation-aware methods accept a final AbortSignal injected by the Gateway; stream Remotes use @Remote({ mode: 'stream' }) returning an AsyncIterable
  - Forwarded Host events reach ctx.remote.$on() through the Gateway-owned $events logical endpoint over a WebSocket with heartbeat keepalive
  - Client faces: $stream() (single-consumer RemoteStream), RemoteSnapshotStream, and RemoteJournalStream with pagination, reconnect catch-up, and gap repair
  - note: Application-call infrastructure; registers no prompt, tool, or session event. Client consumers stay on generated namespaces and $stream() rather than lifecycle control.

**`@deepseek-ai/dsh-api-remotes`** — The application Remote assembly (a two-sided BFF): the Host entry owns the forwarded-event allowlist and registers the application event source with API Gateway, while the Client entry imports generated /remote artifacts, mounts each contribution via ctx.remote.$mount(), and re-exports their declaration merges. Client business packages depend on this facade rather than the Gateway implementation.
  - Mounts the application's selected contributions (Commands, credentials, settings, Goal, dynamic Cordis, Session Controller, Workspace Controller, etc.)
  - API_REMOTE_FORWARDED_EVENTS is the single allowlist of forwarded Host events; each entry selects ordinary or Agent-scoped waterfall delivery
  - Re-exports type-only the wire type vocabulary (RemoteResult, RemoteErrorCode, RemoteHostFacts, client-safe payload types) so client packages import one specifier
  - Owns no physical transport or Host service discovery; API Gateway owns endpoints, carriers, cancellation, and reconnection
  - note: Capability set is fixed by explicit build-time value imports; clients do not discover active Services at runtime.

**`@deepseek-ai/dsh-api-session-controller`** — Owns the Host ctx.sessionController service and the generated Client session, skills, and fileReferences Remote namespaces. It serves Session lifecycle and history, the Host-generation model catalog, workspace-path opening, user-invocable skill discovery, and Agent-scoped file references.
  - History pages and follow snapshots carry one record per durable Session event; the Client journal validates exact V3 envelopes before publishing
  - SessionEventStream is a RemoteJournalStream bound to one ordinary or direct-subagent address, with follow-before-page, loadOlder(), and loadThrough(seq) turn-jump loading
  - Queue mutation and cancellation require live state; create and fork are the only operations that create a new Agent directly
  - Prompt admission consumes opaque fileUpload receipts and resolves every same-Agent receipt before sending content through ctx.attachments
  - SessionMediaReferences mounts GET|HEAD /api/file?path= for authenticated browser file serving
  - config: `nativeOpen`=platform-detected
  - note: Client-facing session control; applies one preset-aware resume policy and subagent ownership fence to its own methods and to the Agent/Session lookups used by other Remote namespaces.

**`@deepseek-ai/dsh-api-settings-controller`** — Host Remote owner for settings and credential configuration surfaces: it exposes generated ctx.remote.settings and ctx.remote.credentials namespaces that return redacted settings and credential metadata, support writes without returning secret values, and open provider-owned settings or Agent preset directories on the Host desktop.
  - describe(refs) answers one map keyed by requested names, capping at 64 names per call
  - Valid set(ref, value) and unset(ref) calls report provider refusal as credential-rejected; no method here returns a secret value
  - settings.describe() returns deployment facts and every namespace under redactSecrets: true
  - settings.openSettingsDocument() and openAgentPresetDirectory() prepare provider-owned documents and open them with native intents; neither accepts a browser-supplied filesystem target
  - config: `nativeOpen`=platform-detected
  - note: When a provider is absent the namespace stays registered and returns an actionable configuration error.

**`@deepseek-ai/dsh-api-workspace-controller`** — Owns the Host ctx.workspaceController service and the generated Client ctx.remote.workspace namespace. Its Remote methods create, rename, remove, and reorder Workspaces, reorder Sessions within a Workspace, archive Sessions from navigation, and follow the complete Workspace projection. It also owns ctx.directoryPickerController and ctx.remote.directoryPicker.
  - Host controller serializes mutations that depend on current registry state and throws RemoteError with stable workspace/* or directory-picker/* codes
  - follow() stream emits one complete baseline first, then ordered upsert, remove, order, and archived increments
  - Reconnect starts a new generation with a replacement baseline, so consumers never depend on every increment while disconnected
  - Client entry provides ClientWorkspaceModel and createWorkspaceStateStream() with stream/unary race resolution (newer row wins by updatedAt)
  - note: Framework-neutral snapshots and subscriptions; navigation policy and React hooks stay with the UI owner.

**`@deepseek-ai/dsh-api-workspace-files`** — Workspace file service for the web GUI: bounded file reads through the composed filesystem (UTF-8 text by page, bounded byte windows or complete files, related-file resolution from a base file's directory, and metadata), plus workspace-scoped directory listing and instrumented filesystem observation. Exposes no mutation operation.
  - Methods: stat, read (line window), readBytes (byte window), readAll, readRelated, list, and changes (a stream Remote)
  - File reads may target paths outside the workspace; list and changes remain workspace-scoped
  - changes relays fs/observed observations inside the Session workspace root as { absolutePath, version } or absent frames
  - Client registers the file resource provider into ctx.resources with dsh-resource://file/session/<sessionId>/<path> addresses
  - Failures are typed RemoteError codes (workspace-file/not-found, too-large, not-text, etc.) declared in ./types
  - config: `maxBytes`=2097152, `maxFileBytes`=33554432, `maxLines`=5000, `maxEntries`=2000
  - note: Registers no tool and contributes no prompt; purely the web-client file-preview surface.

**`@deepseek-ai/dsh-cordis-host-runner`** — Host half of dynamic Cordis packages: definitions the model records with cordis_define stay in process memory, host halves run in a node:vm sandbox, a package with a browser half waits for a person to approve or decline it on a page, and the model can inspect the live runtime (ctx.cordisInspect) and its definitions. The model-facing tools live in dsh-tool-cordis and the browser half loads through dsh-cordis-client-runner.
  - Definitions are session-scoped and process-local — a DSH restart clears them and nothing is written to disk
  - cordis_run activates the current package (mode: run) or switches version (mode: update); cordis_stop ends the live run keeping it runnable; cordis_undefine stops and forgets it
  - A package with a browser half becomes an approval request settled by a page's verdict, with the caller's AbortSignal as the only other exit
  - Sandbox isolates globals and redirects Node globals to Cordis services (ctx.fs, ctx.web, ctx.bash, timers) but is not a security boundary — treat a dynamic package like bash access
  - Four forwarded events (cordis/request-run, cordis/request-run-resolved, cordis/dynamic-package, cordis/dynamic-retract) are allowlisted for browser delivery
  - config: `vmTimeoutMs`=5000
  - note: The self-referential Cordis toolset; definitions are in-memory only and browser-half packages need a connected page or they suspend until the asking turn is cancelled.

**`@deepseek-ai/dsh-cordis-client-runner`** — Browser half of dynamic Cordis packages: it answers the host's run requests, loads the browser-half source into the page as a live plugin, and removes it when the host retracts the run. A person approves or declines a run (or starts one directly), and the resolution this package reports back becomes the cordis_run tool result the model reads.
  - Browser halves are plain JavaScript (no JSX/TypeScript/module imports) run as an async function with a fixed symbol surface: React, console, styles, host
  - Guard is a whitelist of lifecycle verbs plus the services a package declares in its own inject; host.call(method, args) reaches its own host half
  - Post-settle render crashes are reported to the host (reportRenderFailure) with the slot and whether the entry abdicated
  - Loading is idempotent; a refresh starts clean — the host still holds the definition but this page does not run it until asked again
  - note: Requires the host runner and the ui-cordis panel to be composed; host-only packages need no page at all.

**`@deepseek-ai/dsh-typert-loader`** — Loader integration for generated Typert artifacts: with it mounted, every package that mounts in a Loader composition automatically contributes its generated host-face reflection and schemas to the runtime registry, and withdraws them when the package or plugin unmounts. Packages without the generated export are skipped, so adding it to any composition is safe.
  - Discovery defaults to every Loader entry; an explicit `packages` list covers plugins nested behind another Loader entry
  - Registration follows the entry lifecycle — withdrawn on unmount, and a late-settling import is discarded if both owner and plugin are gone
  - validateTypertManifest() is the module/file boundary: the manifest must name the package, carry face host, hold zod v4 schema instances, and use strict codecs
  - Resolution verdicts and imported manifests are cached for the process lifetime, so adding a ./typert export requires a restart
  - config: `packages`=[]
  - note: Node-only plugin needing the config-tree resolution anchor; the registry itself comes from dsh-typert-registry.

**`@deepseek-ai/dsh-typert-protocol`** — The shared Typert Remote protocol: decorators (@Remote, @RemoteScope), wire descriptors, codecs, and provider contracts used by business packages, generated artifacts, the Host Gateway, and the Client API. It declares types and decorator markers only — it registers no Cordis service and runs no TypeScript analysis.
  - Mark a public instance method @Remote (or @RemoteScope(key) for scoped receivers); the owning service extends TypertRemoteService or declares a typertRemote binding via bindTypertRemote()
  - Merge-extensible TypertLookupMap / TypertContextMap associate Host objects and scoped Contexts with wire identities
  - RemoteError carries a stable <domain>/<reason> code with typed details; RemoteErrorDetailsMap is the merge-extensible table packages extend
  - TypertForwardableEvent / TypertClientEventListener derive the ctx.remote.$on listener from an Events member; TypertClientRemote exposes only $mount() and $on()
  - remoteErrorOf(value) reads a structural marker to recognize failures across module or realm copies
  - note: Compiler-independent declarations; full parameter/result/lookup/schema reflection is the Typert build pipeline's job via InvocationDescriptor.

**`@deepseek-ai/dsh-typert-registry`** — The runtime Typert registry (ctx.typert): it stores each package's generated reflection (services, events, objects), its live Zod schemas, and Remote invocation descriptors under stable keys that consumers can query or resolve on demand. Registrations are atomic and fiber-scoped — a contribution lands whole or not at all and is withdrawn automatically when its component unloads.
  - Consumers query with get(key), resolve(key), list(filter?), getPackage(name, face?), listPackages(filter?); toJSONSchema(key) projects a live schema without caching
  - Sub-registries: ctx.typert.local (current-environment invocation definitions), remotes, lookups (lookup providers + per-key resolver overrides), and contexts (Host Context providers and Client Context binders)
  - ctx.typert.lookups/contexts back Remote call resolution of Host objects and scoped Contexts
  - Stable keys: <package>#<face> for reflection, <package>#<name> for schemas, <namespace>/<method> for endpoints; duplicate identities reject the whole batch before commit
  - note: Performs no TypeScript analysis and generates no schemas; the generator and the loader handle those. Host and client faces run the same implementation.


### Human-facing seams & skills — 10 plugins

**`@deepseek-ai/dsh-user-approval`** — Channel-neutral one-shot approval seam: before a sensitive tool action runs, it requires a single human or machine decision. The `ask` policy delegates each request to the deployment's composed answerers, `never` rejects deterministically without prompting, and missing/failed answerers return `unavailable` so the action fails closed; every request and outcome is appended to the requesting session's audit log.
  - ApprovalService exposes `request(req)` naming agent, tool, optional call id and reason, plus an abort signal
  - Answerers are `approval/request` waterfall listeners; deployment composes one terminal answerer, sibling order is not priority
  - Policy is per-session with a configured default; `setPolicy`/`setApprovalPolicy` switch live agents or persist durably
  - Requests must be enclosed in an open turn; aborting settles `cancelled` and a late answer is discarded
  - Model sees only the eventual allowed/rejected/cancelled/unavailable tool outcome plus policy in the runtime-context snapshot; audit events and permission UI are not model context
  - config: `policy`=ask
  - note: The `never` policy is what a delegated agent sees as 'approval prompts are disabled — do not request sandbox escalation'; absence of a terminal answerer fails closed rather than prompting.

**`@deepseek-ai/dsh-user-questions`** — Waterfall-based question-and-answer service owning `ctx.userQuestions`: a model-facing tool or permission plugin pauses work and dispatches an answerer waterfall to get a human decision. It exposes `ask(request)` returning the first accepted answer, and supports Agent-scoped Web answering plus a `plan-review` presentation intent.
  - `ask()` dispatches the answerer waterfall and waits for the first accepted answer
  - Request shape: questions with id, question, optional detail/header/options/multiSelect/intent, plus optional agent and signal
  - Answer shape: `{ answers: [{ id, selected, custom? }] }` with `custom` overriding selected for single-select
  - Authenticates the calling agent through the live AgentRegistry and admits only a runtime root
  - `intent: { kind: 'plan-review', approve }` changes presentation only; UIs that know the tag render it specially
  - note: A live child owned by another agent is rejected (`DELEGATED_CALLER`): the child must include the unresolved question or decision in its final result. `dsh-plan-mode` sets the `plan-review` intent on its exit question.

**`@deepseek-ai/dsh-permission-presets`** — User-facing permission presets that bundle one sandbox mode with one approval policy into a single selector, with a configurable preset table and a default applied to newly created sessions. The `/permission` command reports or switches the current preset; a knob combination matching no preset shows a derived `custom` state that is display-only.
  - Named presets each bundle one sandbox mode with one approval policy; shipped table includes `workspace-write` and `danger-full-access`
  - Default preset is pinned into fresh sessions only; changing the default never alters existing sessions
  - Switching presets changes only the knobs whose effective value differs; matching current preset changes nothing
  - `custom` is derived-only — callers can switch away from an unmatched combination but cannot select or persist it
  - Write path appends `permission/preset` then writes changed knobs through `setSandboxMode` and `setApprovalPolicy`
  - config: `presets`=workspace-write, danger-full-access, `defaultPreset`=inferred
  - note: A presentation/selection package; enforcement is delegated to `dsh-sandbox-policy` and `dsh-user-approval`. Requires a confining bash executor reporting `sandboxMode` plus the approval service.

**`@deepseek-ai/dsh-plan-mode`** — Per-agent plan mode: the agent explores and designs before executing, then presents the finished plan for user approval. It is entered with `/plan` (optionally with a message or ordered image/file attachments), left with `/plan off`, and closed through the `exit_plan_mode` reviewed exit where the user chooses Approve or Keep planning with feedback.
  - Deployment-defined `section` guidance is rendered as the `plan:policy` prompt section while plan mode is active
  - `/plan`, `/plan <message>`, `/plan off`; the message becomes the next request under plan guidance
  - `exit_plan_mode` presents the markdown plan for an Approve / Keep planning decision
  - Every tool stays callable — plan mode restrains through text, not capability filtering
  - Durable state survives session resume and forks; state is log-only whole-value fold
  - config: `section`=required
  - note: Forked agents inherit logged plan state while newly spawned agents begin inactive; a live child owned by another agent fails `exit_plan_mode` and must include the unresolved decision in its final result.

**`@deepseek-ai/dsh-commands`** — Human slash-command registry for interactive UIs: plugins register `/command [input]` actions that run directly against an agent without creating a model message. It supports command discovery, input hints, attachments, agent-scoped shadowing, and records every admitted run in the receiving agent's session log while the UI renders the result outside model history.
  - `ctx.commands.register()` takes a lowercase name, description, optional input hint, and a handler running against the receiving agent
  - Handler returns `success` or `error` plus optional UI text; `recordInput` defaults to true
  - Agent-scoped commands shadow global definitions of the same name for one agent
  - Optional `input.attachments` accepts composer images and generic files; enforcement happens in the executor
  - `execute()` mints a commandId and appends `command/run`/`command/done` lifecycle events; unknown or malformed lines are rejected, not prompted
  - note: Command discovery, execution, and UI output add no model tokens; UI-less demos and ACP automation provide no command adapter.

**`@deepseek-ai/dsh-native-command`** — Library (not a plugin — no ctx, no state, no events) that runs host executables without a shell and opens Host filesystem paths through the desktop. `runNativeCommand` captures utf8 stdout/stderr and propagates cancellation; `openNativePath`/`openNativeTextFile`/`revealNativePath` handle default-app, text-editor, and file-reveal intents with WSL path translation.
  - Shell-free execution via Node `execFile`; the `NativeCommandRunner` type is an injectable testable boundary
  - Non-zero exit rejects with `code`, `stdout`, `stderr`, and original error as `cause`
  - Open intents: default application, text editor (`open -t` on macOS), browser-renderable documents, and desktop reveal
  - `canOpenNativePath()` reports whether the Host plausibly has a desktop target; `nativeFileManager()` names the action
  - WSL paths translated with `wslpath -w` before reaching the Windows desktop; callers must authorize the absolute path first
  - note: No output bounding — both streams buffer unbounded in memory; intended for small native tools whose output is a path or one error line.

**`@deepseek-ai/dsh-authorization`** — Authorization flow registry that obtains credentials a human must hand over — an OAuth-style sign-in, one-time code, or account pick — through a human-guided session. A plugin registers a flow per credential it holds; any surface runs an attempt and the interaction travels with the requesting surface, reporting `authorized` only after the new credential is committed to the credential store.
  - `registerFlow({ key, label, methods, run })` declares the `<scope>/<id>` credential record the flow writes and its sign-in methods
  - `run(session)` talks to the human through one-way `notify` and `prompt` (text/secret/select); the flow must commit via `ctx.credentials`
  - `begin()`/`cancel(key)` manage one attempt per credential at a time; `list()`/`describe()`/`dispose()` surface and withdraw flows
  - A declined prompt or withdrawn signal settles `cancelled`; any other failure throws
  - Commit confirmation re-reads the record after run() resolves, so `authorized` always means it was stored now
  - note: A configuration-time human conversation; no flow, notice, or prompt reaches a model request. Provides no provider-specific methods itself — flows are plugin-registered.

**`@deepseek-ai/dsh-skill`** — Skill provider registry: it merges skills from local directories, embedded plugin data, or remote services into one catalog, resolves duplicate names predictably, validates entries, tolerates unavailable sources, and loads a selected skill's full instructions on demand. It includes no skill content itself and is paired with `dsh-skill-filesystem` for local discovery and `dsh-tool-skill` for model access.
  - One merged catalog: consumers ask for a workspace catalog and get every winning summary sorted by name
  - On-demand loading returns the full body from the owning provider, re-validated against a stale-selection check
  - Providers register with `registerProvider`; plugins register in-memory skills with `register`; `runtime` is a reserved provider name
  - Invocation policy (`modelInvocable`/`userInvocable`) decides which surfaces advertise and load a skill
  - Layered host+per-scope resolution; nearest layer wins, duplicates resolve by rank then registration order
  - config: `collectCacheMaxEntries`=128
  - note: The registry applies to every agent, including subagents, which load the same session catalog; a duplicate name is first-wins with no API to inspect shadowed definitions.

**`@deepseek-ai/dsh-skill-badge`** — Bundled immutable 'powered by dsh' badge skill provider: when enabled, the `dsh-badge` skill appears in the session catalog so agents can follow its instructions for adding attribution badges to documents, pull requests, and other content produced with DeepSeek Harness. It ships Markdown snippets and a packaged PNG for systems that cannot reliably import remote images.
  - Registers exactly one fixed candidate at bundled skill rank 600 under provider name `dsh-badge`
  - Markdown instructions for embedding official badge markup in documents, PRs, and merge requests
  - Packaged `dsh-badge.png` asset (726x120 source, rendered at 121x20) for targets that cannot fetch remote images
  - No configuration; shipped CLI composition carries the row as `disabled: true`
  - note: Immutable provider: discovery always succeeds with exactly one skill and never reports partial results; remote Markdown relies on Shields.io.

**`@deepseek-ai/dsh-skill-filesystem`** — Local filesystem skill provider: it scans the project, custom, and user skill roots, parses each skill's YAML frontmatter into a catalog entry, loads the body on demand, and watches the roots so new, renamed, or deleted skills reach agents without a restart. Skills are a directory bundle `<name>/SKILL.md` or a flat `<name>.md` under any scanned root.
  - Scans default roots in rank order: project `.dsh/skills`, `.agents/skills`, custom dirs, user `.dsh/skills`, user `.agents/skills`
  - Frontmatter: required `name` and `description`, optional `whenToUse`, `metadata`, `disable-model-invocation`, `user-invocable`
  - Strict boolean grammar for invocation keys; a rejected spelling drops the whole skill with a warning
  - Chokidar watcher at depth 1 plus missing-root probing; first-party `write`/`edit` invalidate synchronously
  - Catalog and body have separate lifecycles — every load re-reads the current file, so body edits need no cache invalidation
  - config: `providerName`=filesystem, `includeDefaultRoots`=true, `dshHome`=$DSH_HOME or ~/.dsh, `agentsHome`=$DSH_AGENTS_HOME or ~/.agents, `customSkillDirs`=[], `watch`=true
  - note: Discovery is one level deep (only `<root>/<name>/SKILL.md` and `<root>/<name>.md`); project scope is the nearest `.git` ancestor, else the supplied cwd. Requires `ctx.skills`.


### Client host & plumbing — 14 plugins

**`@deepseek-ai/dsh-client-connection`** — Provides the browser-to-Host wire layer for the web GUI: it mounts ctx.connection with current-page loopback state, generic Remote RPC, the active connection generation and Host facts, observable recovery state, and an immediate reconnect command. It also owns browser authentication (launch-token to signed cookie) and the Host/Origin request-trust fence that defends DNS rebinding and cross-site requests.
  - Remote RPC plus exact GET/HEAD/POST route registries; the /api HTTP bridge and WebSocket remote.mux
  - Connection generations with onConnected published only after a ready item; invalidates on ended/errored/malformed streams
  - Retry policy with 50-100% jitter under caps 500ms-10s and continuous recovery until online
  - Browser auth: launch token on GET / -> authority-bound signed cookie (HttpOnly, SameSite=Strict), 401 before RPC dispatch
  - Request-trust fence: loopback or trustedHosts Host check, Origin equality, refuses sec-fetch-site: cross-site
  - config: `cookieMaxAgeDays`=30, `config.recovery`=default caps (500ms-10s), `maxRequestBodyBytes`=300 MiB, `trustedHosts`=none
  - note: Explicitly model-experience: none — it moves already-composed messages and touches no provider request.

**`@deepseek-ai/dsh-client-file-upload`** — Lets browser features store a Blob, exact bytes, or a ReadableStream<Uint8Array> for one Session and receive an opaque receipt for a later prompt, via ctx.fileUpload.upload(sessionId, body, name, signal, onProgress). Streams are consumed once and transferred across the Worker boundary; the Host plugin (ctx.fileUploads) owns the authenticated streaming route, receipt resolver, and staged-receipt lifecycle.
  - Serves Blob and stream bodies without aggregating bytes on the page thread
  - Blob uses XMLHttpRequest in a dedicated Worker for real upload progress (total when provided)
  - ReadableStream transfers to the Worker and feeds Fetch incrementally (consumed-byte progress, no total)
  - AbortSignal terminates the dedicated Worker or reaches a page-owned carrier
  - Staged receipts bound to the receiving Session, consumed during prompt admission; durable result types
  - note: No Cordis config fields. Uploads are not resumable and stream bodies are one-shot.

**`@deepseek-ai/dsh-client-hmr`** — Development-only hot reload for browser client plugins: when a plugin bundle is rebuilt (by a pnpm run dev:web-style watcher), the browser swaps that one plugin in place with fresh component state while the data layer (connection, runtime, Session objects) stays untouched. Nothing observable happens in a production build.
  - Node half stat-polls graph bundles and broadcasts rebuilt frames; serves /plugins/events SSE channel
  - Browser half prefetches and registers the new factory, then swaps fiber with registry-first teardown
  - Dependent plugins reload automatically via fiber activation-epoch cascading
  - No rollback on failure: an import failure leaves the entry fiberless and retries on next rebuild
  - Only a real revision change reloads; a map-only write does not re-execute code
  - config: `pollIntervalMs`=500
  - note: React state inside the reloaded plugin is lost; session/workspace/connection state survives.

**`@deepseek-ai/dsh-client-locale`** — Localization for the web GUI: switches between shipped English and Chinese (and languages added by client plugins), with browser-derived fallback, typed namespace dictionaries, and a framework-injected t seat. User selections take effect immediately; loopback pages persist the preference in $DSH_HOME/settings.yaml while non-loopback pages keep it process-local.
  - ctx.locale.register(ns, {zh,en}) registers typed namespace dictionaries, compiler-checked per namespace
  - ctx.locale.addLanguage({ id, label, fallback }) registers external language packs with fallback chains terminating at en
  - Browser-derived provisional locale (navigator.languages by full tag then primary subtag, en fallback) until Host settings arrive
  - Slot-rendered copy updates live without a remount; bound translate functions keep stable identity
  - Host half persists preference via the settings service only on loopback pages
  - note: Nothing needs configuration to mount; the plugin activates with the client tree.

**`@deepseek-ai/dsh-client-modules`** — The client module system for the web GUI: the host half scans enabled Loader entries, validates each package's dsh.client declaration, composes the boot graph, and serves plugin bundles over /plugins; the browser half loads those bundles lazily. Plugins execute lazily under a lazy-CJS model — running a bundle only registers a factory, and module side effects run at materialization.
  - Host composes the normalized boot graph and injects window.__DSH_BOOT__ with '<' escaped
  - Frozen PLATFORM_MODULES baseline (React, Cordis, static UI libs) with dsh.client.external for non-baseline requests
  - Lazy-CJS model: factories memoized in loadCache; require cycles throw; resolution checks seed table, memoized records, boot rows, factories
  - Incremental per-package composition with no full-rescan path; bundle content changes reach the graph only via HMR rebuilt()
  - Groups resources into immutable /plugins combo URLs (<=3 KiB each), Indexed Source Map v3
  - note: Accepts no plugin config of its own. Requires pnpm run build to have produced each lib/client.js before launch; a missing bundle fails activation loudly.

**`@deepseek-ai/dsh-client-resources`** — The client resource model: protocol-registered providers turn URL addresses (dsh-resource://<type>/…) into live values that any slot component reads through the useResource standard hook. Components receive the current value and later updates; unsupported protocols and non-resource schemes resolve to no resource.
  - useResource<P>(address) returns { status, value, failure } with none/loading/live/failed states
  - One provider per protocol; ctx.resources.register opens held addresses and disposal ends their streams
  - ctx.resources.pin(address, signal) keeps a resource open without subscribing (e.g. Sidebar tab record lifetime)
  - ctx.resources.source(address) is the bare observable for callers outside React
  - Failures are ok:false frames, not throws; shared stream per address with holder-count refcounting
  - note: Nothing needs configuration to mount; the plugin provides ctx.resources and contributes the resource root-keyed hook.

**`@deepseek-ai/dsh-host-directory-picker`** — The workspace-directory picking seam for the web GUI host: an abstract DirectoryPicker Cordis service exposing a single capability() method, plus the capability vocabulary (native or browse) and a closed DirectoryPickerError code set. It is only the service contract — a composition without a backend has no way to pick a directory.
  - DirectoryPickerCapabilities is a merge-extensible map; new backends declaration-merge their shape here
  - capability() returns a discriminated union: { kind:'native', pick(signal) } or { kind:'browse', list(path?), createDirectory(path,name) }
  - Typed DirectoryPickerError with closed codes directory-unreadable / directory-exists / directory-create-failed, each carrying the subject path
  - DirectoryEntry rows expose absolute path and host-owned hidden flag (dot-prefixed on POSIX)
  - DirectoryListing.crumbs is the root-to-target ancestor chain; every crumb is a jump target
  - note: Directory picking is limited to the GUI host and never affects the agent loop. Only one backend may mount (second registration throws duplicate-service).

**`@deepseek-ai/dsh-host-directory-picker-auto`** — Adaptive chooser of the directory-picker seam: it samples the host's situation once at boot and mounts the matching native or browse backend (plus its browser half) as real Loader entries in the in-memory root tree. native requires a loopback-only bind, a non-SSH launch, and a servable display session; anything ambiguous resolves to browse, which works everywhere.
  - One pure boot-time decision via resolveDirectoryPickerBackend; the mounted capability stays stable for the service lifetime
  - Resolution table: non-127.0.0.1 bind -> browse; SSH_CONNECTION/SSH_TTY -> browse; darwin/win32 -> native; linux with chooser binary + display -> native
  - Mounts the backend and surface packages as real Loader entries, never persisted to a config file
  - Pinning an interaction means composing the -native or -browse row directly (mounting both together fails loud)
  - Probe reads inherited SSH_* env only (ignores project/user .env) and checks PATH for zenity/kdialog
  - note: No config field for pinning — compose the concrete backend row directly. A wrong native choice degrades to the backend's retryable failure dialog.

**`@deepseek-ai/dsh-host-directory-picker-browse`** — In-app browsing backend of the directory-picker seam: it lists one directory level and creates child directories from the browser using Node's standard library, rendering nothing on the host display — so it serves remote clients that cannot reach an OS chooser. One composition row also fills the workspace flow's directory holes with the in-app Select Workspace Directory dialog.
  - list(path?) returns name-sorted child directories with absolute paths, hidden flag, home anchor, and crumbs
  - createDirectory(path, name) is non-recursive and validates a single non-blank path segment (no separators, not . or ..)
  - Bounded O(maxEntries) name-sorted window keeps memory flat regardless of directory size; cut level reports truncated: true
  - Fully-qualified fence refuses relative/rooted-drive-less forms on Windows
  - AbortSignal stops an in-flight scan via raceAbort; typed DirectoryPickerError mapping
  - config: `maxEntries`=1000
  - note: Windows hidden attribute is not read (dot-prefixed on every platform); no drive-root enumeration.

**`@deepseek-ai/dsh-host-directory-picker-native`** — Native-OS-chooser backend of the directory-picker seam: opens one platform directory chooser per pick and resolves the chosen absolute path (null on cancel). macOS drives osascript, Linux uses Zenity with a KDialog fallback, and Windows opens the modern IFileOpenDialog in a spawned child process. Only viable when the operator sits at the host's display.
  - pick(signal) resolves to the chosen absolute path or null on cancel; aborting the signal terminates the chooser process
  - Runs as a subprocess so the host process never blocks on the dialog; no-shell subprocess runner via dsh-native-command
  - Windows IFileOpenDialog via koffi in a child process, with per-monitor-v2 DPI and WM_CLOSE abort
  - Linux requires Zenity or KDialog; with neither, pick rejects with an actionable error (no typed-path fallback)
  - One composition row also registers the matching renderless browser-side interaction in the workspace flow
  - note: Windows foreground grant relies on injected Alt input (validated on Windows 11 only); browse backend is the composition-level fallback.

**`@deepseek-ai/dsh-host-frontend-static`** — SPA dist server for the Web shell: it claims the webserver's single fallback seat and serves the built frontend from its configured distribution directory. Root and configured index paths render the bootstrapped index (with Connection authorizeIndex for token/cookie), existing assets are served directly, traversal returns 403, missing/non-file paths return 404, and unsupported methods return 405.
  - distIndex config resolves the dist root and the configured index path
  - Every successful index response is rendered through the webserver's renderIndex so the boot manifest reaches the page
  - Traversal fence (using sep, not '/', for Windows) rejects paths resolving outside the dist root with 403
  - Index access requires a valid process token or browser cookie; static assets remain public
  - Single-owner fallback seat: a second activation throws, and unclaimed seat answers 404
  - config: `distIndex`=required
  - note: Minimal MIME table: covers Vite-emitted assets plus the shipped PWA manifest; unknown extensions fall back to application/octet-stream.

**`@deepseek-ai/dsh-host-open-in-app`** — Host half of open-in-app: it resolves installed editors, Git GUIs, terminals, and file managers to verified launchers on macOS, Windows, and Linux, and serves the catalog, icons, and launch endpoint as three webServer routes (GET /open-in-app/apps, GET /open-in-app/icon/<id>, POST /open-in-app/open). It shows only entries the host can verify and launches are credential-scrubbed and never shell-based.
  - Fixed compile-time catalog: editors/IDEs, Git GUIs, terminals, and per-platform file managers
  - Each source yields a verified launcher (an artifact this host actually holds), never a bare install record
  - Per-platform resolution: macOS known app dirs + xcode-select; Windows App Paths/Uninstall records; Linux CLI + XDG desktop entries
  - SSH launch (non-empty SSH_CONNECTION/SSH_TTY) makes the app list empty and hides Open In
  - Lazy one-pass resolution per host process; new installs appear after restart, uninstalls self-heal; real icons served per platform
  - config: `probeTimeoutMs`=required, `iconTimeoutMs`=required, `launchWatchMs`=required
  - note: Requires webServer, connection, and subprocess; pairs with dsh-client-ui-open-in-app. Catalog is fixed at build time — no user-added apps from cordis.yml.

**`@deepseek-ai/dsh-host-plugin-inventory`** — Read-only projection of the current Cordis Loader plugin state plus each agent preset's flattened composition, exposed as the pluginInventory service and its pluginInventory/list Remote for web GUI host clients. Each call reads ctx.loader.entries() and maps each non-group entry to a public row with identifier, module specifier, effective enablement, and live root-fiber phase; with an agent-preset roster it also reports preset metadata, health, and composition.
  - Rows carry entry id, exact module specifier, effective enablement (including disabled ancestor groups), and fiber phase
  - Phase vocabulary: pending/loading/active/failed/unloading, with null meaning no live root fiber
  - agentPresets reports per-preset id, trust, display name, whether unnamed sessions compose it, and flattened plugin rows
  - Point-in-time, read-only snapshot for display and diagnostics; it cannot enable/disable/add/remove plugins
  - Remote-only service; deliberately declares no same-process Context merge; no cache, no history, no subscription
  - note: Presets appear only with a dsh-agent-presets roster; the agentPresets field is absent (not empty) without one.

**`@deepseek-ai/dsh-host-webserver`** — The web GUI host's HTTP server: a node:http server where other plugins register named routes, upgrade routes, index startup inputs, and one fallback handler. It knows no harness concepts and serves no files — the /api bridge, plugin bundles, the HMR event stream, and the SPA dist belong to the plugins that register them. Route matching is fixed: exact, then longest prefix, then the fallback handler.
  - register(route) adds exact/prefix HTTP routes; registerUpgrade(route) adds an exact-pathname upgrade route; both return disposers
  - Single fallback seat via registerFallback(handler); a second registration throws, unclaimed seat answers 404
  - Index startup inputs: collectIndexInjections() gathers webserver/index-inject rows, renderIndex(html) renders them then applies raw tapIndex transforms
  - Optional gzip compression with a compression threshold; SSE, ZIP, range, and no-transform responses untouched
  - Host accepts exactly 127.0.0.1 (default) or 0.0.0.0; port 0 requests an OS-assigned port read via ctx.webServer.port
  - config: `host`=127.0.0.1, `port`=3000, `compression`=none, `compressionThresholdBytes`=1024 (shipped Web bundle)
  - note: A listen failure (e.g. EADDRINUSE) rejects plugin initialization with the bind diagnostic; a handler throw answers 400 or destroys the socket.


### Client UI (A) — 24 plugins

**`@deepseek-ai/dsh-client-ui-agent-preset`** — Provides the Web GUI surfaces for choosing an agent preset: the new-session chip (opens on the deployment default and stages a pick for the next blank session), the session-header label showing the active preset, and a Settings roster section for copying, making default, deleting, or locating presets. A preset is fixed when a session is created, so changes affect only later sessions; if no presets are provided, all controls hide and every session uses the host composition.
  - New-session chip and session-header label driven by one staged-choice controller
  - Settings roster cards: copy dialog (only creation route), make-default, delete, and open-in-files actions
  - Self-referential `cordis` preset renders a dashed add-card that starts a new session
  - Broken roster rows show as marked cards with body/duplication disabled
  - note: Reads/writes the `agent-presets` settings namespace `default` field; roster re-reads on its own actions, settings/document-updated, and connection/reset.

**`@deepseek-ai/dsh-client-ui-approval`** — Browser approval presentation over the Agent-scoped Remote Event waterfall: publishes each pending Host permission request through ctx.uiSession, takes over the Conversation composer, optionally renders correlated Tool detail, and returns the user's decision (allow-once or reject) to the waiting Host request.
  - Takes over the composer to collect a decision for a pending Host operation
  - Supports allow-once and reject; persistent policy stays Host-side
  - Optional correlated Tool-detail rendering
  - note: Transient decisions only; approval request/response does not alter a model request.

**`@deepseek-ai/dsh-client-ui-attachment`** — Renders everything the conversation UI shows about attachments: the ordered draft-attachment rail under the composer, a full-viewport drop invitation, durable images in Chat, Trajectory, and Tool results, and an Escape/mask/close lightbox for the original image. Attachment data, upload state, and callbacks come from the declared slot owners.
  - One non-wrapping draft rail with 64px image thumbnails and 240px file cards
  - Per-message gallery with count-based sizing and click-to-open original
  - Full-viewport drop overlay announcing accept/reject state
  - Shared history gallery across Chat, Trajectory, and Tool results

**`@deepseek-ai/dsh-client-ui-brand-official`** — Gives an `official` client build the DeepSeek Harness mark and name in the sidebar; other build profiles keep the shell's fish mark and local-build label, while the conversation hero always uses the animated fish. Replacing it requires another package occupying the same slots.
  - Occupies sidebar.brand.mark and sidebar.brand.name only in official builds
  - Profile-gated registration via DSH_CLIENT_BUILD_PROFILE
  - Conversation hero uses the animated fish regardless of profile
  - No runtime state and no model effect
  - config: `DSH_CLIENT_BUILD_PROFILE`=unset (shell fallbacks), `DSH_CLIENT_TITLE`=build-configured

**`@deepseek-ai/dsh-client-ui-chat`** — Renders a browser Chat target from recorded Session conversations: session nodes, historical images, localized actions, and restored scroll position. Compact mode (default) folds completed-turn process rows while keeping the final answer and system prompt visible; local submissions appear immediately and are replaced when authoritative Session records arrive. File-mention providers receive the viewed Session ID so links into inherited history address the fork.
  - Normal/Compact conversation-display preference (Compact default) with turn-process folding
  - Per-turn token-usage disclosure when exact usage is available
  - System prompt row per nonempty appended system message
  - Turn-rail previews and semantic scroll restoration across history prepend
  - config: `conversation display preference (ui-chat namespace)`=Compact

**`@deepseek-ai/dsh-client-ui-commands`** — Client command API for the Web GUI: a `/` source that resolves a command line against the session's command directory and dispatches it as a registered popup, a host command's input, or a direct execution. Business packages register command surfaces through ctx.commandUi, and a command line is never silently downgraded to a plain prompt.
  - Three dispatch kinds: popupSelect, leadingInput, and execute
  - ctx.commandUi.register and decorate for business command surfaces
  - Per-session CommandDirectory cache with epoch guards and change/connection invalidation
  - Attachment-carrying submissions only allowed for commands declaring input.attachments
  - note: Space/Enter resolve against the session directory; detached results notify the session composer via SessionInput.notify.

**`@deepseek-ai/dsh-client-ui-conversation`** — Owns target-neutral Conversation assembly and the shared browser shell: event and view registries, per-Session bindings, input state, slots, and temporary composer takeovers. It exposes React-free registries via ctx.uiConversation and the useConversation/useInput/inputActions standard props via ctx.uiSession, plus a per-session durable image URL cache. Concrete targets (e.g. Chat) are separate packages registering their own Definitions, snapshot builders, Views, and renderers.
  - Single UiConversation.events and UiConversation.views registries with duplicate-key rejection
  - Per-session durable image URL cache resolving one session-authorized URL per attachment
  - Shell-owned Lexical composer with reference chips, queue dock, and draft persistence
  - Temporary composer takeovers via the conversation.composer chain
  - Deterministic view selection (persisted selection, else chat, else none)
  - config: `maxConcurrentFileUploads`=2, `busy-Enter behavior (ui-conversation settings namespace)`=persisted setting
  - note: Continuable subagents disable attachment intake because their transport does not preserve the browser request id.

**`@deepseek-ai/dsh-client-ui-cordis`** — Adds frame-wide control panel, conversation tool cards, and `@pluginId` completion for dynamic Cordis packages in the web client. A person can approve or decline a blocked model run request from any session, run, stop, or remove definitions, and inspect live status; conversation cards replay recorded calls and results. Definitions are process-local and must be run again after a reload.
  - Frame-wide panel with badge count, per-definition run controls, and live status
  - cordis_define / cordis_run / cordis_stop / cordis_undefine replay-stable cards
  - @pluginId input source offering the current session's defined plugins
  - Frame-wide approvals so any tab can answer a blocking run request
  - note: Adds no model-visible content and writes no session events; approvals/declines leave no session-log trace.

**`@deepseek-ai/dsh-client-ui-deliverables`** — Renders the deliverables row a finished turn ends with — files created or modified by mutation tools — and links matching inline-code references in the closing prose so a mentioned file opens in the Host. The vocabulary comes from the mutation tools' locations, never from the prose, and explicit deliveries require the `present` tool. The shipped Web patch is the only composition that loads this package.
  - Files changed row listing successful file-tool mutations
  - Explicit `present` deliveries shown as cards with Sidebar-preview and native-Open menu
  - Inline-code mention links resolved by exact path or unique basename
  - Injects a static system-prompt section instructing the model to name and format file references
  - note: Adds a fixed system-prompt paragraph at first-party order 9000; KV-cache stable across Turns.

**`@deepseek-ai/dsh-client-ui-directory-picker-browse`** — In-app directory-browsing surface for the Web GUI: a Miller-column 'Select Workspace Directory' dialog that lists, navigates, and creates folders through the local Host, with no OS chooser. It fills the two directory-flow slots declared by ui-workspace; choose it when the browser is remote or in-process and no local OS chooser exists.
  - 680x500 Miller-column dialog with path breadcrumb and editable path zone
  - New folder dialog and Open fallback to the listed level
  - Prefix filtering of the last pane and a hidden-entry toggle
  - Host-flagged hidden entries stay hidden until the footer toggle reveals them

**`@deepseek-ai/dsh-client-ui-directory-picker-native`** — Native directory-picking surface for the Web GUI: a renderless browser occupant opens the operating system's own chooser on the machine running the Host and reports a single outcome (picked path, cancellation, or failure). It fills the two directory-flow slots declared by ui-workspace; choose it when the browser runs on the same machine as the Host.
  - Opens the host OS folder dialog for a workspace-directory request
  - Single outcome reported to the owner's latest handlers
  - Arms once per rising open edge, so re-renders never launch a second chooser
  - note: No per-request abort on the wire; an HMR unmount discards the settlement. Local Host carriers only.

**`@deepseek-ai/dsh-client-ui-goal`** — Web goal surface showing both the durable goal state and its current process-local activation, with edit, pause, resume, and clear verbs; rejected changes appear inline. It also projects durable `/goal` runs as 'Command input' bubbles so commands from users or the model remain visible after reload. Goal creation stays outside this package.
  - Composer-context strip as the second card (after Todo, before Queue)
  - Four mutation verbs: edit objective, pause, resume, clear
  - Command-input bubble projection for durable /goal runs
  - Inline Remote error on rejected mutations; loading/absent/completed render nothing

**`@deepseek-ai/dsh-client-ui-input-trigger`** — Input trigger pipeline for the Web GUI: detects `/` and `@` under the caret, opens a grouped candidate menu for slash commands, file references, and session references, and routes picks to registered sources. Supports keyboard and pointer selection including drill-down choices; a pick invokes a command flow or inserts a reference for the consuming input surface.
  - Pure core (detect/reduce/match) with zero React/DOM/cordis dependency
  - Grouped candidates under title rows with crumb headers
  - Space/Enter adjudication via optional matchSpace/matchEnter hooks
  - Drill action (Tab or chevron) for second-level selection

**`@deepseek-ai/dsh-client-ui-jobs`** — Renders the background-job surface of the Web GUI: a session-header action opening a popover listing the jobs this session can see, with a badge counting running and stopping jobs. It reads host-computed registry state through the runtime's jobsBySession mirror and issues no RPC; rows are read-only and settled rows stay de-emphasized until the registry drops them.
  - Session-header trigger only when the session has at least one job
  - Badge counts running plus stopping, omitted at zero
  - Live rows ordered by start time, settled rows by finish time
  - Per-second ticking elapsed duration that freezes at completion

**`@deepseek-ai/dsh-client-ui-layout`** — Provides the Web GUI's three-column AppFrame, edge-column widths, and ctx.layout presentation control. The right column concedes space before the center and its occupant renders fullscreen while the frame keeps the wide-screen track underneath; the theme presenter owns color scheme, alias tokens, content font size, and document metadata. Layout state resets on reload.
  - Sidebar 264-420px (default 280px, 56px collapsed rail), auto-collapse below 1024px
  - Right panel opens at 45% viewport, retains pixel preference capped at 70%
  - ctx.layout.selectPanel/toggleSidebar/openRightbar/closeRightbar methods
  - Theme presenter projecting color-scheme, tokens, font-size, and theme-color meta
  - config: `sidebar width`=280px (range 264-420px), `right panel width`=45% of viewport, capped at 70%

**`@deepseek-ai/dsh-client-ui-message-feedback`** — Web feedback surface: the Like/Dislike pair in the finalized assistant message's action strip, the feedback dialog collecting a category and optional description, and a `/feedback` decoration opening the dialog for the Session. Ratings, categories, and notes are log-only Session events that never enter model context.
  - Like/Dislike both open the dialog; a recorded rating shows the filled glyph
  - Seven category chips and optional detail box; Submit records the judgment
  - Bare /feedback opens the Session dialog; /feedback <text> keeps the Host command
  - One controller per Session backs every message control and dialog
  - config: `maxNoteBytes`=8192 in the Web bundle

**`@deepseek-ai/dsh-client-ui-model-selection`** — Lets Web users switch the model and reasoning effort for an existing session through either the `/model` popup or the composer's model seat, both presenting the same provider-grouped per-session directory. The selected model determines the available effort names and default; a complete selection applies to the next request, while a running step keeps the model and effort it started with.
  - Two entries over one per-session ModelDirectory (ctx.modelDirectories)
  - Provider-grouped models; /model popup shows catalog descriptions
  - Effort levels from the selected model's adapter metadata; no arbitrary effort input
  - Unroutable session raises a composer block, recovered without a reload
  - note: Addressed subagent sessions expose neither entry.

**`@deepseek-ai/dsh-client-ui-open-in-app`** — Browser surface of the open-in-app feature: a Session-header split button whose main button opens the session's workspace directory (the summary's cwd) in the remembered application, and whose chevron lists every catalog application the host probed as installed. Availability, icons, and launches come from the host package dsh-host-open-in-app.
  - Main button launches the remembered app; chevron lists installed applications
  - Real app icons (macOS bundle, Windows exe, Linux theme) with generic fallback
  - Persisted choice (dsh.open-in-app.choice) with fallback when uninstalled
  - Busy treatment after 250 ms; failed launch shows error tooltip and red outline
  - config: `dsh.open-in-app.choice`=none (first available entry used)

**`@deepseek-ai/dsh-client-ui-permission-presets`** — Lets Web users choose permission presets for future sessions or switch the current session. The General-settings row changes only the default for sessions created later, while the `/permission` picker changes only the current session and marks its active preset. Built-in presets use localized labels; full access always requires explicit risk acknowledgement.
  - General settings row writes the host's defaultPreset for later sessions
  - /permission popupSelect decoration replaces only the bare invocation
  - Built-in labels Read Only / Workspace Write / Full access (and Chinese equivalents)
  - Full-access option carries a confirmation payload rendered as an in-page risk gate
  - config: `defaultPreset (permission settings namespace)`=host dynamic enum

**`@deepseek-ai/dsh-client-ui-plan`** — Renders the plan-mode status chip in the Web GUI: when the host-computed projection's effective target is plan mode, the composer shows a warn-colored 'Plan x' button that executes `/plan off`; otherwise the seat stays empty. Plan mode itself belongs to dsh-plan-mode; this package only renders the projection and sends what a user could equally type.
  - Warn-colored 'Plan x' button in the conversation.input.plan seat
  - Executes /plan off and maps admission failures to an inline error
  - Placeholder switches to the plan-task hint while plan mode is active
  - Renders nothing when plan mode is inactive or no session exists

**`@deepseek-ai/dsh-client-ui-reference`** — Web `@file` and `@session` reference source for the composer: one completion menu listing files before sessions, keeping either group available when the other cannot load. Picking a file, folder, or session inserts an atomic reference with a stable clipboard form; folder rows let users descend without closing completion. Session mentions are validated before model context is captured, while browsing candidates has no model effect.
  - Files-first, then sessions ordering with locale-registered section labels
  - Atomic file and folder references; drill action descends while the menu stays active
  - Canonical @[label](dsh-session:...) mention for session picks
  - Quoted @"path with spaces" support and retained explicit quotes

**`@deepseek-ai/dsh-client-ui-renderer`** — Infrastructure that mounts the assembled dsh web client GUI: after the complete client plugin roster settles, the boot kernel calls ctx.uiRenderer.mount(container), which hydrates the framework-free boot page and switches to the full React application before the next paint. Business plugins stay plain React components receiving typed props; the renderer binds the runtime's observable sources into selector hooks at the slot outlets.
  - ctx.uiRenderer.mount(container) hydrates boot DOM or creates a fresh root
  - Sole context-level renderSlot('root') call
  - Binds runtime observable sources into selector hooks via useSyncExternalStore
  - Preserves a single React identity through the web shell's static module table

**`@deepseek-ai/dsh-client-ui-schedule`** — Renders a read-only catalog of the current Session's active Schedule reminders in the Web header. It reads the complete `schedule` projection, issues no RPC or mutation, and derives status, local time, relative time, and ordering in the browser without adding them to durable state. The shipped Web bundle keeps the plugin disabled until the explicit Schedule overlay enables it.
  - Session-header trigger only when the projection has at least one active record
  - Overdue rows first, then future rows by target time
  - Browser-local target time, relative time, and interval formatting (never rounded)
  - Body-portaled popover with keyboard dismissal and 16px viewport margins
  - note: Enabled via `dsh web --patch apps/cli/config/examples/schedule/cordis.yml` together with @deepseek-ai/dsh-schedule.

**`@deepseek-ai/dsh-client-ui-session`** — React and Slot adapter for Session Controller state: contributes Session list and pending-interaction hooks at root scope, materializes per-Session hooks and props, and owns the standard SessionProvider rendering behavior without taking ownership of Session transport or lifecycle state.
  - Root-scope Session list and pending-interaction hooks
  - Materializes per-Session hooks and standard props
  - Standard SessionProvider rendering behavior
  - Enforces Session binding consistency in the adapter materialization path
  - note: Pending interactions are process-local projections; the owning Remote waterfall must replay an outstanding request after a browser reconnect.


### Client UI (B) — 16 plugins

**`@deepseek-ai/dsh-client-ui-settings`** — Browser-side settings domain base for the dsh web client: it owns the settings-namespace scope service (ctx.settingsScope) and schema service (ctx.settingsSchema), and declares the canonical settings slot-type contract. Feature plugins bind a per-namespace scope to read and edit Host-backed preferences without implementing their own transport or schema handling.
  - Inject remote with a 'settings' namespace and own the single settings.describe mirror reader in the browser
  - ctx.settingsScope.bind(spec) returns a per-namespace scope derived from the shared document mirror
  - Atomic ordered writes via mutate, fenced by namespace revision (expectedRevision) to refuse concurrent changes
  - ctx.settingsSchema performs synchronous rehydration, validation, and immutable path editing
  - Declares settings.section, settings.plugins.tab, settings.onboarding slot types; renders no interface itself
  - note: Browser-only UI layer, registers nothing model-facing. Non-loopback pages get no durable settings (Host persistence disabled there).

**`@deepseek-ai/dsh-client-ui-settings-general`** — The settings shell of the dsh web client: renders the modal Settings panel, the navigation built from settings.section entries, the sidebar Settings trigger with connection-recovery states, and the sequential onboarding ledger. Feature packages supply their own rows, sections, and onboarding steps; this package supplies only shared presentation.
  - Settings panel reachable from the sidebar bottom seat (sidebar.settings)
  - Connection recovery indicator with Disconnected/Reconnecting/Connected states and Reconnect now action
  - General section (settings.general.item) has no built-in rows; features own the copy and behavior
  - Open configuration file action on loopback browsers via settings/openSettingsDocument
  - Onboarding ledger mounts exactly one step at a time, each registrant owning its own completion
  - note: Browser-only UI layer. The General section cannot fill itself; every row needs its owning feature plugin mounted.

**`@deepseek-ai/dsh-client-ui-settings-models`** — The Models settings page of the dsh web client: lets users configure provider API keys (stored write-only under the profile's credential reference), edit each provider's model list, and hand-declare custom pi-ai routes. It also drives first-run onboarding through a versioned internal-testing notice and a conditional official-DeepSeek credential step.
  - One API key input per editor card, stored write-only via credentials.set under the profile reference
  - Curated fold fields: baseURL, per-adapter model catalog, display name and API protocol for pi-ai routes
  - Add/delete providers, with Fetch available models using llm/discoverModels before creating
  - Settings writes fenced by card revision; a concurrent change is refused as settings/conflict
  - Extension slots settings.models.provider-card and settings.models.footer for out-of-repo plugins
  - config: `apiKey`=none, `baseURL`=unset, `models`=inherited, `displayName / apiProtocol`=unset, `contextWindow / maxTokens`=unset
  - note: Browser-only UI layer. Only API key and curated fold fields are editable on the card; other advanced fields stay in settings.yaml.

**`@deepseek-ai/dsh-client-ui-settings-plugin-inventory`** — A read-only Plugin list tab in the Web Plugins settings section: lets users inspect the Host's plugin inventory without changing configuration. It presents agent presets first, collapses the global plane behind a disclosure, and supports search across both groups.
  - Lazily calls ctx.remote.pluginInventory.list() on first tab selection (no Remote read during activation)
  - Cards show short module name, stable entry id, enablement tag, runtime status dot, provenance, and disabled conditions
  - Preset-provided global entries name the presets that enable them, with a jump into the preset group
  - Preset switcher (selector-pill-plus-menu) filters the list only; writes no settings
  - Handles loading, empty, no-match, failure, and retry states without exposing transport details
  - note: One snapshot per Settings mount or retry (does not subscribe to Loader changes); read-only in both planes, no enable/disable writes.

**`@deepseek-ai/dsh-client-ui-settings-plugins`** — The Plugins settings section of the dsh web client: presents one expandable card per host-plane plugin (bash executor, agent-loop parallelism, subagent-model-selection, web-search-deepseek) for editing, and hosts feature-specific plugin pages. Cards stage edits locally until save and are refused if the config changed after load.
  - Plugin configuration tab dispatches one card per served settings namespace via the settings.plugins.tab slot
  - Subagent card stages a permission switch and exact-model checkboxes, saving enabled and allowedModels atomically
  - Reset stages the composed default rather than writing immediately; Discard drops drafts
  - Secret-role fields write through the credentials domain, not the settings section
  - Declares the nested settings.plugin.item slot keyed on the settings namespace a card edits
  - config: `subagent-model-selection.enabled`=false, `subagent-model-selection.allowedModels`=[], `agent-loop`=deployment, `web-search-deepseek`=deployment
  - note: Only host-plane plugins appear; a plugin an agent preset mounts carries its config inline and cannot register a settings namespace. The Subagent card directly governs subagent model routes and permission.

**`@deepseek-ai/dsh-client-ui-sidebar`** — The sidebar navigation shell of the dsh web client: shows the brand row, New Session action, collapse to a 56px rail, a scroll-aware region seat, and a bottom-pinned Settings seat. Feature plugins fill its seats via slots such as sidebar.workspaces and sidebar.settings.
  - Brand row renders sidebar.brand.mark and sidebar.brand.name as independent single slots
  - New Session targets an explicit Workspace, else the current Session's, else the most recently active, else a blank page
  - Collapse animates to a 56px rail with reduced-motion disabled transitions
  - sidebar.panellist root-scoped list for global panel entries with id/order/locale-aware label
  - Rebinds scrollbar indirection to transparent when the pointer is outside the column
  - note: Session state-dot rendering, Workspace browser behavior, and unread marking are owned by other plugins, not this shell.

**`@deepseek-ai/dsh-client-ui-sidebar-documentpreview`** — Document previews in the right Sidebar: previews readable files (Markdown, code, images, PDF, HTML, plain text) without opening another tab. Markdown and code receive accumulated text pages; PDF, HTML, and common images receive complete bytes; unknown extensions fall back to plain text.
  - Registers a tab type (kind text, pattern dsh-resource://file/**, band fallback) plus keyed body under sidebar.right.pane.tab
  - Renderer registry via ctx.documentPreviews.register (extension > builtin > longer suffix > registration order)
  - HTML fills edge-to-edge in a Blob iframe with sandbox=allow-scripts only
  - Code previews show source line numbers by default without including them in copied text
  - Supports source-line navigation (openResource with { params: { line } })
  - note: Preview only, no editing or shared search; PDF/HTML/images bounded by the Host maxFileBytes cap. Nothing the user reads here enters a model request.

**`@deepseek-ai/dsh-client-ui-sidebar-files`** — The right Sidebar's file-tree tab type: lists the session's workspace root as a tree, one level at a time over the wire (remote.workspaceFiles.list), and opens files into the Sidebar by resource address. It is a page type reached from the guide and claims no address of its own.
  - Registers a type (kind files, band builtin, no patterns) plus one guide entry (order 10)
  - Root is the session working directory from useSessions().byId[sessionId].cwd
  - Rows ordered directories first, then natural case-insensitive name; dotfiles shown normally
  - File rows open dsh-resource://file/session/... via tab.actions.openResource
  - Per-level loading/empty/failed states; reload drops levels and refetches expanded ones
  - note: Listing only: no search, rename, drag-and-drop, context menu, or filesystem watching. One root — no browsing above the session working directory.

**`@deepseek-ai/dsh-client-ui-sidebar-right`** — The right Sidebar of the dsh web client: holds one docking surface per session, drawn as an edge-anchored panel in the frame's right column in push or fullscreen presentation. It owns the navigation controller ctx.sidebarRight, the tab-type registry ctx.sidebarRightTabs, and the Tab domain that tracks how each open tab was navigated to and how long it lives.
  - push (default) and fullscreen presentations share the same content tree, so switching does not remount tabs
  - ctx.sidebarRightTabs.register for tab types; ctx.sidebarRight.openResource/openTab for navigation
  - Extension seats sidebar.right.tab.guide (chain) and sidebar.right.tab.menu.item (list)
  - Guide page with entry capsules that open contributing types as pages
  - Tab domain retains navigation, an abort signal, and bound actions per (Session, tab id)
  - note: Memory-only (a reload starts every session collapsed). The dockkit owns layout/gestures; this package supplies the product copy and tab-kind meaning.

**`@deepseek-ai/dsh-client-ui-skill`** — Web skill references and the skill tool row: lets users invoke a skill by choosing it from the / suggestions or typing /name directly. The same literal command loads the skill consistently from the Web composer, TUI, and ACP; skill calls appear in the conversation as expandable Instructions cards whose settled contents stay stable when the catalog changes.
  - Slash source registering into the inline suggestion machinery; the sent message carries literal text
  - Candidates from the skills/list Remote, ranked via rankByName (case-insensitive ordered subsequence, prefix first)
  - modelInvocable: false skills wear a user-only marker prefix in the active language
  - Skill call card registers the 'skill' wire name in ui-tool's keyed tool.call.toolview slot
  - Row derives name/lifecycle/body only from the frozen call/result slice, never the current catalog
  - note: Model-facing behavior: the host's pre-step boundary appends the canonical <skill_content> block as injected context for the turn, paid unconditionally. A name shared with a host command resolves to that command.

**`@deepseek-ai/dsh-client-ui-theme`** — Theme and content-font-size settings for the dsh web client: users choose light, dark, or system and set conversation content text from 12 to 17px in Settings. It ships the --dsw-* token stylesheets and a synchronous bootstrap so the selected palette and font size apply before the shell loads, and publishes immutable ThemeSnapshot objects.
  - Registers Appearance preference cubes and a font-size stepper in the General section (default 14px)
  - Persists in the ui-theme settings namespace ($DSH_HOME/settings.yaml on loopback)
  - System resolved through prefers-color-scheme; ui-layout applies each snapshot to the document
  - Six token stylesheets (base, corner-shape, design-platform, scrollbar, gradient-shadow-text, shiki) owned by the plugin
  - ctx.theme lets third-party themes register alias-token overrides; pre-plugin palette embedded into index responses
  - config: `contentFontSize`=14, `colorScheme`=not documented
  - note: Non-loopback pages keep both choices process-local. Token sheets are the sole color authority; third-party themes are an extension point without completeness validation.

**`@deepseek-ai/dsh-client-ui-tool`** — The client Tool presentation plugin: renders every tool call in the conversation as a root call tree with nested subcalls, dispatching each atomic call through the keyed tool.call.toolview slot. Business UI packages register only their wire Tool names and atomic views; the Runtime stays authoritative for call/result pairing and recursive subCalls.
  - Root and Code Dispatch children rendered by ToolCallTree; atomic calls dispatched by wire tool name
  - Built-in views for shell/pwsh, read, read_image, write/edit, str_replace_editor, grep/glob, web, todo, question, Code Dispatch
  - Unregistered Tool names use the generic card
  - Owner payload ToolCallOwnerProps includes callId, frozen block, cwd/home, loadImage, openFile/inspect
  - Path summaries relativize to Session cwd then replace a leftover POSIX home with ~
  - note: Renders logged calls without changing model context. First-party tool views are colocated here but can move to owning packages through the keyed slot.

**`@deepseek-ai/dsh-client-ui-trajectory`** — The Trajectory view in the conversation's view ring: a turn-aware event ledger with an interactive timing overview. It groups User, Assistant, Tool, nested Subtool, and compaction records, marks turn and step boundaries, and opens a record inspector for token usage, duration, input, output, timing, images, and attachment summaries.
  - Ledger over the shared Session window with virtualized rows (initial 50 target Nodes at the tail)
  - Timing overview projects real start/duration; drag to focus, wheel to zoom, right-drag to pan
  - Long histories load older pages on demand and render only visible rows
  - During streaming the view follows the tail until the user scrolls upward
  - In-flight records show a start marker without inventing elapsed time
  - note: Pure projection of the shared Session window; reads no Chat snapshot and emits no cordis events. Provides no service.

**`@deepseek-ai/dsh-client-ui-user-questions`** — The Web ask_user_question feature: when an agent asks a question, it replaces the chat composer with an interactive question surface. Users can move through questions, choose single or multiple options, enter custom answers, skip items, and submit one structured answer batch; a plan-review intent renders a dedicated approval card.
  - Composer-takeover question UI with pager, multi-select, custom answers, and skip
  - Single-choice selections advance immediately; Enter submits once all questions are answered or skipped
  - Plan-review card with Chat about it / Refuse / Approve actions
  - Drafts survive Session navigation for the page's lifetime in a non-persisted Slot store
  - Bilingual chrome under the 'question' namespace of dsh-client-locale
  - note: Renders the dsh-tool-ask-user schema and answers; the host remains authoritative for pending status. A subagent calling ask_user_question is refused (DELEGATED_CALLER), so this surface serves the owning agent.

**`@deepseek-ai/dsh-client-ui-workflow-run`** — A durable workflow-run Conversation Node: reconstructs each top-level workflow run (via dsh-tool-workflow) as an independent chat node with nested phase and member disclosure. Running, failed, cancelled, and interrupted levels open by default; completed levels stay closed. It shows identities and statuses only.
  - Replays tool-workflow/run-start and member events deterministically into one Context keyed by runId
  - Run -> phases -> members disclosure; status updates without removing or reordering members
  - A running member can open its child Session only when it belongs to the current Session and is available locally
  - Completion delays its automatic close while focus remains inside the content
  - Registers Definition, locale dictionary, and workflow-run renderer as Cordis effects
  - note: Surfaces subagent-origin members: a member row is interactive only when origin is 'subagent', parentId is the current Session, and the list row is still running. Only top-level calls through dsh-tool-workflow produce these records.

**`@deepseek-ai/dsh-client-ui-workspace`** — The shared Workspace browser and picker: lets users browse grouped or flat Session lists, choose a Workspace for a new Session, and manage Workspaces and Sessions via add, rename, reorder, search, fork, and archive. Pending interactions show as warning dots, active scheduled tasks as alarm markers, and subagent-origin Sessions stay hidden.
  - Grouped or flat Session lists with Manual / Last updated session order (browser-persisted per account)
  - Search with case-insensitive title/Workspace matches plus debounced Host content matches (capped at 20)
  - Rename, archive, fork (at last completed turn), and Workspace delete actions
  - Pending-interaction warning dots (approval / plan review / answer) and scheduled-task alarm markers
  - Directory-flow child hole filled by a composed picker (native OS chooser or in-app -browse dialog)
  - note: Pure consumer registering into host-declared slots (sidebar.workspaces, conversation.hero.workspace.directoryFlow). No fuzzy content search or Session deletion/unarchive; native folder selection depends on the local Host carrier.


### Foundation (cordis/cosmokit/addons) — 10 plugins

**`@deepseek-ai/cordis`** — Core TypeScript plugin framework that provides the dependency container (Context), a plugin registry and fiber lifecycle, scoped services, events, and a built-in logger. Plugins declare required services via `inject`, and all effects/listeners/services are removed when their owning fiber is disposed.
  - `new Context()` creates the root dependency container
  - `ctx.plugin()` starts a plugin and returns a Fiber
  - `inject` declares required services that must exist before a plugin runs
  - Scoped services and events with `ctx.on` / `ctx.emit`
  - Lifecycle-managed cleanup: effects and listeners removed on fiber dispose
  - note: The core all other cordis packages build on; required to understand plugin lifecycle, services, and config-driven loading.

**`@deepseek-ai/cordis-plugin-group`** — Loader group plugin that nests Cordis entries, so one group entry can carry a child entry list and those children can be enabled/disabled as a unit. Groups are always considered enabled themselves; disabling the group entry prevents its child entries from running.
  - Nests entries under a `group: true` entry whose `config` is a child list
  - Disabling a group prevents all child entries from running
  - Nested child ids use `:` separators (e.g. `tools:logger`)
  - Re-exports the `Group` implementation from @cordisjs/plugin-loader as its default plugin
  - note: Thin wrapper re-export; used inside loader configs to organize plugin trees.

**`@deepseek-ai/cordis-plugin-hmr`** — Hot module replacement for loader-managed Cordis plugins. It watches source files, traces Node's module graph, clears affected module caches, and reloads only the plugin entries that depend on changed app files; framework-level changes fall back to `loader.exit()` so the host restarts.
  - Chokidar-based file watching over configured roots
  - Module-graph tracing to reload only affected plugin entries
  - Falls back to loader.exit() for framework-level dependency changes
  - Emits `hmr/change` and `hmr/reload` events
  - Canonicalizes base directories before opening watches
  - config: `base`=None, `root`=['.'], `ignored`=None, `debounce`=None
  - note: Requires @cordisjs/plugin-loader and @cordisjs/plugin-timer, plus a runtime exposing Node's internal module loader (throws otherwise).

**`@deepseek-ai/cordis-plugin-include`** — File-backed loader tree for Cordis: it reads a YAML or JSON file, turns it into loader entries, and writes updates back when the file is writable. Patches can insert entries or override fields on entries with a matching id.
  - Loads a plugin tree from a YAML or JSON config file
  - Writes updates back to the file when writable
  - Writes an `initial` entry list when the file is missing
  - Runtime `patches` applied after reading the file
  - Optional loader apply/reload/unload logs via `enableLogs`
  - config: `path`=None, `initial`=None, `patches`=None, `enableLogs`=None
  - note: The standard way compositions are defined on disk; relevant when editing cordis.yml-style composition files.

**`@deepseek-ai/cordis-plugin-loader`** — Runtime plugin loader for Cordis. It owns an EntryTree, imports plugin modules by name, applies their config, and keeps the running plugin graph in sync with entry updates.
  - Owns the EntryTree and imports plugin modules by name
  - Applies per-entry config and keeps the running graph in sync
  - Create/update/remove/resolve entries, including nested `a:b` ids
  - `loader.await()` waits for pending imports and fiber reloads
  - `loader.locate(fiber?)` returns the loader entry id that owns a fiber
  - config: `id`=None, `name`=None, `config`=None, `group`=None, `disabled`=None, `inject`=None
  - note: The runtime that drives composition mounting; central to diagnosing whether a preset actually mounts.

**`@deepseek-ai/cordis-plugin-timer`** — Disposal-aware timer service for Cordis. Provides timeout, interval, throttle, and debounce helpers whose handles are registered on the current fiber, so they are cleared automatically when the plugin that created them is disposed.
  - `ctx.timeout` runs once and returns a disposer, or returns a promise
  - `ctx.interval` repeats and returns a disposer, or yields an async iterator
  - `ctx.throttle` and `ctx.debounce` return callables with `.dispose()`
  - Handles auto-cleared on fiber disposal
  - `setTimeout`/`setInterval` kept as deprecated aliases
  - note: Dependency of the HMR plugin; useful for any plugin needing disposal-safe scheduling.

**`@deepseek-ai/cosmokit`** — A collection of common utility functions available as a single import, usable from both Node.js and Deno.
  - Bundles common utilities behind a default import (`import cosmokit from 'cosmokit'`)
  - Runs in Node.js and Deno (via `npm:cosmokit@latest`)
  - No per-feature documentation in the README
  - note: README is minimal; capability beyond 'common utilities' is not documented here.

**`@deepseek-ai/schemastery`** — Type-driven schema validator usable as either a validation function or a constructor. Supports union, intersect, and transform types, custom schema types via Schema.extend, and JSON serialization so schemas can be hydrated in another environment.
  - Schemas are callable as validators or constructors
  - Advanced types: union, intersect, transform, dict, tuple, const
  - Custom types via `Schema.extend(type, resolve)`
  - Serializable to JSON and hydratable elsewhere
  - `simplify()` removes parts equal to schema defaults
  - note: Instance methods: required, default, description, simplify; `default` and `required` are mutually exclusive.

**`@deepseek-ai/node-addon-system`** — JavaScript entry for the prebuilt Landlock launcher and asynchronous POSIX flock. The `./landlock-run` entry exports the launcher path, enforcement probe, grant arguments, and protocol constants; the independent `./flock` entry exports `tryLockExclusive(fd): Promise<void>`. Importing either entry does not load `system.node`, and the package has no root export.
  - Separate `landlock-run` and `flock` entries; no root export
  - `tryLockExclusive` attempts LOCK_EX | LOCK_NB asynchronously
  - Contention rejects with EAGAIN/EWOULDBLOCK; errors carry code, errno, and `syscall: 'flock'`
  - Native setup errors reject the same promise; no install-time compilation
  - OS/CPU platform packages carry the binaries; C sources ship for auditability
  - note: Binding does not open, duplicate, close, or explicitly unlock descriptors; caller keeps the descriptor open until completion.

**`@deepseek-ai/node-addon-system-linux-x64`** — Prebuilt Landlock launcher and POSIX flock addons for Linux x64. Contains the static musl executable `bin/landlock-run` plus Node-API v8 addons `bin/glibc/system.node` and `bin/musl/system.node`; the entry selects the addon matching the running Node process's libc, and the Landlock executable serves both libc systems.
  - Ships prebuilt binaries only; no JavaScript or install build script
  - Addon selected by the running Node process's libc (glibc/musl)
  - Landlock executable serves both libc systems
  - Platform prepack checks payloads, ELF architecture, Node-API exports, and launcher executability
  - note: Installed-artifact rehearsal checks bytes and executes native behavior.


---

## 5. Cross-cutting seams & capabilities

These are the abstract seams (a contract + one or more backends) that most capability groups hang
off. Each is a `ctx.<name>` service unless noted.

- **`ctx.fs`** (`dsh-fs`, backends `dsh-fs-local`, `dsh-fs-sandbox`) — text IO + version-guarded
  atomic mutations; `dsh-fs-observation-policy` adds read-before-edit; the sandboxed backend fences
  write/edit by per-call mode.
- **`ctx.shell`** (`dsh-shell`; executors `dsh-bash-local`/`dsh-bash-sandbox`,
  `dsh-pwsh-local`/`dsh-pwsh-sandbox`) — platform bash or PowerShell; the sandbox variants confine
  every command and report denial/enforcement facts.
- **`ctx.sandbox`** (`dsh-sandbox`; `dsh-sandbox-local` bwrap/landlock/Seatbelt/Windows-ACL,
  `dsh-sandbox-policy`, `dsh-sandbox-windows-acl`) — same-world confinement, fail-closed,
  functionally probed at boot.
- **`ctx.subprocess`** (`dsh-subprocess`, `dsh-subprocess-local`) — managed process groups, bounded
  spill-backed output, escalated kills.
- **`ctx.terminal`** (`dsh-terminal`, `dsh-terminal-bash`) — persistent PTY sessions, owner-scoped
  ids, interactive sends/reads/signals, awaited cleanup.
- **`ctx.spillStore`** (`dsh-spill`, `dsh-spill-local`, `dsh-spill-policy`) — save oversized tool
  text and return a retrieval locator; the policy replaces oversized plain-text results with a
  preview + spill path.
- **`ctx.codeRuntime`** (`dsh-code-runtime`, `dsh-code-runtime-worker-thread`) — the code-execution
  seam behind PTC tool presentation.
- **`ctx.llm`** (`dsh-llm`; adapters `dsh-llm-deepseek` `deepseek-official`, `dsh-llm-pi-ai`
  multi-provider; `dsh-llm-retry` on top) — token streaming, model discovery, capability resolution,
  deep-frozen requests, provider-neutral failure codes. Only path into providers.
- **`ctx.web`** (`dsh-web`; providers `dsh-web-fetch-http`, `dsh-web-search-deepseek`) — search/fetch
  with a registration-order-independent provider selection and a `WebError` taxonomy.
- **`ctx.settings`** (`dsh-settings`, `dsh-settings-file`) and **`ctx.credentials`**
  (`dsh-credentials`, `dsh-credentials-local`) — settings.yaml + `$DSH_HOME/.env` secrets;
  credentials cannot be isolated from the agent (tool processes run as the same OS user).
- **`ctx.storage`** (`dsh-storage`, `dsh-storage-json`, `dsh-storage-domain`) — named backend
  registry + schema-validated event-emitting KV domains. `single` JSON rewrites the whole unit per
  write (route high-volume to SQLite).
- **`ctx.sessionPersistence`** (`dsh-session-persistence`, `dsh-session-persistence-jsonl`) — the
  durable log; `dsh-session` is the event-sourced in-memory store deriving model history;
  `dsh-session-checkpoint-policy` flushes at semantic barriers; format migration is v0→v1→v2→v3.
- **`ctx.sessionProjections`** (`dsh-session-projection`, `dsh-session-projection-cache`) and
  **`ctx.sessionQuery`** (`dsh-session-query`, `dsh-session-query-sqlite` FTS5) — derived read
  models over the log. The query DB must never point at the persistence DB.
- **`ctx.sessionReferenceResolver`** (`dsh-session-reference`) — cross-session snapshot references
  and durable untrusted model context (`@file`/`@session`), with a bounded auto budget.
- **`ctx.subagents`** (`dsh-subagent`) — see §2. **`ctx.jobs`** (`dsh-jobs`, `dsh-jobs-local`),
  **`ctx.workflowEngine`** (`dsh-workflow`, `dsh-workflow-worker-thread`), **`ctx.goal`**
  (`dsh-goal`, `dsh-goal-round-driver`), **`ctx.userQuestions`** (`dsh-user-questions`),
  **`ctx.approval`** (`dsh-user-approval`), **`ctx.skill`** (`dsh-skill`, `dsh-skill-filesystem`,
  `dsh-skill-badge`) — the delegation-adjacent seams.
- **`ctx.directoryPicker`** (`dsh-host-directory-picker` + auto/browse/native backends),
  **`ctx.workspaceRegistry`** (`dsh-workspace`), **`ctx.fileReferences`**
  (`dsh-file-reference`, `dsh-file-reference-local`) — host GUI / workspace / `@file` plumbing.
- **`ctx.tokenMeter`** (`dsh-token-meter`), **`ctx.permissionPresets`** (`dsh-permission-presets`),
  **`ctx.systemPrompt`** (`dsh-system-prompt`), **`ctx.timeContext`/`ctx.tmuxContext`** — context
  and policy providers.

**Profiles / surface bundles:** `web` (`dsh-web-app` + `dsh-web-frontend`), `headless`
(`dsh-headless`), `sdk` (`dsh-sdk-app`), `sdk-minimal` (`dsh-sdk-minimal`, no subagents), `acp`
(`dsh-acp-app`). All base-backed ones ride `dsh-base`.

---

## 6. Known limitations & gotchas (aggregated)

Cross-package constraints worth remembering when you compose a profile or write a skill:

- **Subagent depth cap defaults to 3** on the tool, `0` forbids delegation; exceeding it throws
  `SubagentDepthError`. The seam itself has no service-level default.
- **A delegated subagent cannot widen its own authority.** Approval is auto-rejected
  (`DELEGATED_CALLER` for `ask_user_question`), so a skill must not rely on a subagent asking the
  user — fold the unresolved question into the final result.
- **Continuable messaging is adjacent-only** (direct child ↔ direct live parent); no durable parent
  mailbox, so a missing parent rejects child-to-parent delivery. Wake gap during cancellation
  convergence; pending injected context retains an Activation; process-local residency.
- **Background runs don't return a result through the tool.** One-shot jobs are collected with
  `job_output`/`job_kill`; continuable children deliver a settlement notice and are queried by id.
- **`subagent_fork` cannot select a child LLM route** (keeps provider/model equal to the parent for
  KV-cache reuse). Non-routing child policy (persona/filter/depth) is fixed per tool instance —
  different policy needs another named tool.
- **The workflow worker/vm is not a security boundary** — escaped code reaches the worker's process
  authority; hostile scripts need a separate-process or container engine. One worker thread per run.
- **`dsh-session-query-sqlite` must never point at the persistence DB** (separate derived index).
  `dsh-session-query` is never mounted alone.
- **`dsh-session-persistence-jsonl` requires a `root`** (a `process.cwd()` default was explicitly
  rejected). `dsh-session-projection-cache` and `dsh-session-title` need projections + storage rows
  mounted below them.
- **A patch entry replaces the whole matched config**, it does not deep-merge. Adding a plain
  filesystem provider on top of the sandboxed one makes the profile fail to load.
- **`dsh-atomic-write` is atomic but not crash-durable** (no fsync). `dsh-credentials-local` cannot
  isolate secrets from the agent. `dsh-http-proxy` is a library, not a mountable plugin.
- **Skills: portability is the default.** No `allowed-tools`/`model`/absolute paths/`~/` paths/bang
  backticks unless scoped `harness: [claude]` exactly (Claude's loader executes a bang-backtick
  sequence at load time even inside a code span). The dsh skill provider reads fixed roots; an
  installed package's `skills/` is invisible unless bridged.
- **`dsh-goal`/`dsh-tool-goal` require a direct human root turn**; `dsh-tool-present` must be called
  by the parent. `dsh-schedule` tools install on root Agents only — runtime children never get them.
- **`dsh-plan-mode`**: forked agents inherit plan state, newly spawned agents start inactive; a live
  child owned by another agent fails `exit_plan_mode` and must include the unresolved decision.

---

## 7. Staleness audit vs. this repo's skills/docs

This is the concrete gap the subagent changes opened. The repo's docs and skills were largely
written against dsh `0.1.1-rc.2`/`0.1.2` and describe a narrower delegation surface.

- **`delegate_agent` vs the native dsh subagent tools are different features.** `delegate_agent`
  is the marketplace **bridge** tool that dispatches a *module-defined* agent type
  (e.g. `feature-dev:code-explorer`) on pi/dsh — **`modules/feature-dev/skills/feature-dev/SKILL.md:28`**
  uses it correctly for that, so it is **not** stale. The **native dsh ad-hoc delegation surface** is a
  family of tools: `subagent`, `subagent_fork`, `subagent_codex`, `subagent_claude_code`,
  `send_message`, `interrupt_agent`, `list_agents`, `list_subagent_models`, `workflow`, `ralph`.
  The one stale usage this audit found — `get-shit-done-claude`'s `run` skill naming
  `delegate_agent` for an *ad-hoc* implementer/verifier retry — went away with that module
  (removed 2026-09-16). For ad-hoc delegation on dsh the native tool is `subagent`, or
  `subagent_fork` to seed the child with the parent's completed turns, not the bridge.
- **`docs/spikes/dsh-subagent.md`** documents the one-shot `ctx.subagents.start()` path accurately,
  but predates (or omits) the **continuable** path (`startContinuable()`), the **fork** backend,
  **background subagent jobs**, **per-child model selection**, and the **model-facing tool set** —
  see §2. It should be extended or annotated, not treated as the full story.
- **`docs/superpowers/specs/2026-09-14-feature-dev-cross-harness-agents.md:27-30`** cites
  `ctx.subagents.start()` per-call `persona`/`toolFilter`/`agentOptions`/`maxDepth` — correct for the
  seam, but does not mention continuable children, the control tools, background jobs, or the
  subagent-model-selection session preference, all of which now exist.
- **`docs/install-dsh.md`** was verified against dsh `0.1.1-rc.2`; it was re-verified against
  `0.1.5-rc.2` on 2026-09-16 and its install/smoke claims now match the installed harness.
- **`modules/agent-transcripts/*`** model transcripts as `kind: main | subagent`. With continuable
  children and fork-seeded children, the dsh transcript export/query should treat a continuable
  child session as its own addressable session (stable id) and a fork child as a distinct lineage,
  and the transcript-export-dsh skill should reflect the current session-log format.
- **The subagent-model-selection preference** (a session-level allowlist of exact provider/model
  routes) is not described anywhere in the repo's skills; it changes how a skill should phrase
  "use a cheap model for the subagent" (a route may be rejected by the allowlist, not just by cost).

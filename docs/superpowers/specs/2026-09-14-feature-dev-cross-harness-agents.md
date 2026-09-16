# feature-dev as a cross-harness module: `agents/` consumed natively on Claude Code, pi and dsh

Status: scoped, awaiting go-ahead for implementation. Date: 2026-09-14.
Sources verified this session: dsh 0.1.5-rc.2 and pi 0.84.1 as installed, the official
`feature-dev` plugin (cache `022b3c274938`), this repo's gate, and the maintainer's harness
layer (private).

> **Historical record — do not update.** The `get-shit-done` module referenced below was
> removed from the repo on 2026-09-16.

> **Update note.** The verified seam facts below describe dsh's **one-shot programmatic** seam
> (`ctx.subagents.start()` with per-call `persona`/`toolFilter`/`agentOptions`/`maxDepth`). dsh
> `0.1.5-rc.2` also ships the **continuable** path (`startContinuable()`, durable child + inbox),
> the **`fork`** backend, **background subagent jobs**, **per-child model selection**, and the
> model-facing tool family (`subagent`, `subagent_fork`, `send_message`, `interrupt_agent`,
> `list_agents`, `list_subagent_models`, `workflow`, `ralph`). The bridge's per-call seam call
> remains correct; for a module-defined agent type (`feature-dev:code-*`) the dsh surface is the
> `delegate_agent` bridge tool, while ad-hoc delegation uses the native `subagent` tool. See
> `docs/dsh-plugin-capabilities.md` §2.

## Decisions taken (final)

1. Bridges, not degradation: `agents/*.md` becomes a real dispatchable agent type on all three harnesses.
2. pi bridge ships with its tool registered but **inactive by default**; the PR is gated on a
   `pi/audit` measurement showing ~0 standing tokens while inactive.
3. dsh discovery covers profile bundles in the core bridge, and marketplace live-mounted clones
   as a second commit inside the existing `marketplace` plugin, ranked below bundles.
4. `model:` aliases resolve through a bridge config map, empty by default (inherit parent). On dsh a
   route is passed only if the session's subagent model allowlist permits it.
5. An `agent-contract/` mirrors `hook-contract/`: author-facing README here, executable corpus in
   the harness layer, both bridges graded against it.
6. Delivery order: harness-layer PR first, marketplace PR second, smoke against installed bridges.
7. Module name `feature-dev`; the official plugin is disabled by the user. Agent addressing on every
   harness is `feature-dev:code-explorer` (module:agent). Tool-name translation reuses the
   hook-contract table; unknown Claude tools are dropped with one stderr line. Agents from installed
   packages are user-scope and trusted like their skills. The skill stays portable (no `harness:`).

## Verified seam facts the design rests on

- dsh `ctx.subagents.start(provider, request)` takes `persona`, `toolFilter {allow}`, `agentOptions`
  and `maxDepth` **per call** (`dsh-subagent/lib/types/types.d.ts:136-192`). `dsh-tool-subagent`
  fixes one persona per tool at apply time, so the bridge calls the seam directly with one dispatcher
  tool. Its model allowlist lives in the tool, not the seam (`dsh-tool-subagent/lib/index.js:97`),
  so the bridge replicates that check.
- dsh persona text is rendered with strict `{{name}}` interpolation; unknown names throw
  (`dsh-system-prompt/lib/types/index.d.ts:186-189`). Single braces are safe; `{{` pairs are not.
- pi has no agent concept: `RESOURCE_TYPES` is a closed list (`package-manager.js:67`). An extension
  must read `~/.pi/agent/settings.json` packages and glob `modules/*/agents/*.md` in the clone.
- pi `input` fires before skill expansion but is **skipped** when an extension command matches
  (`docs/extensions.md:884-902`), and `skill-commands.ts` registers `/<skill>` as extension commands,
  injecting `<skill name="...">` blocks (`skill-commands.ts:64,102`). Activation therefore keys off
  the injected block in `before_agent_start`, which covers `/feature-dev`, `/skill:feature-dev` and
  pasted text alike.
- pi child isolation: `-ne -ns -nc -na --no-session` plus an env guard, proven in
  `docs/spikes/pi-background.md:96-97`. The upstream example omits these.
- The 2026-08-11 pi removal (dotfiles commit `882a544c`) cited standing schema cost, an RPC transport
  break, and a 46-minute hang on local-model fan-out. Inactive-by-default fixes the first; the RPC
  break concerned `--mode rpc` deltas and the example uses `--mode json`; the hang needs a per-child
  timeout and concurrency cap, both new.
- Marketplace gate: no lint walks `agents/`; only `claude plugin validate` (CI) checks agent
  frontmatter; a skill may reference `../../agents/x.md` within its module
  (`bin/lint-skills.py:129-132`). The get-shit-done cookbook already forward-references
  `feature-dev:code-reviewer`.

## Architecture (synthesis of three designs)

Shared across harnesses: **data, not code**, as with hooks. Per-harness bridges own discovery,
parsing, translation and dispatch; the contract corpus grades both.

### Harness layer (the maintainer's private dotfiles repo)

`agents/agent-contract/` (new, mirrors `agents/hook-contract/`)
- `README.md`: manifest shape (`name` = filename, `description`, `tools` comma string, `model`
  alias, `color` ignored), Claude→pi and Claude→dsh tool tables, model-alias resolution, `{{`
  neutralization rule, `module:agent` naming, fidelity table.
- `fixtures/*.md` (the three feature-dev agents plus edge cases: unknown tools, `{{` in body,
  missing description), `expected/*.json` normalized `AgentDefinition {type, description,
  systemPrompt, claudeTools[], model}`, `corpus.json` index. Both bridges' tests load it.

`agents/harnesses/dsh/plugins/packages/module-skills/` (touch)
- `lib/roots.js`: add `subdir = 'skills'` parameter to `discoverBundleSkillDirs`/`resolveRoots`;
  export `resolvePackageDir`. `package.json` exports `./lib/roots.js` and `./lib/frontmatter.js`.
  Extend existing discovery tests with an `agents` case. Bump version.

`agents/harnesses/dsh/plugins/packages/module-agents/` (new, `@davidallada/dsh-module-agents`)
- `package.json`: peerDeps `@deepseek-ai/{cordis,dsh-tools,dsh-subagent}`; dep on
  `@davidallada/dsh-module-skills` for roots/frontmatter (workspace, packed version).
- `cordis.patch.yml`: one insert row, config `{dirs: [], provider: 'spawn', modelRoutes: {},
  maxDepth: 1, timeoutMs: 600000}`.
- `lib/catalog.js`: roots → `AgentDefinition[]`; Claude→dsh tool inversion; drop unknown tools
  with one `process.stderr` line; neutralize `{{` in bodies; key `<module>:<name>` where module
  is the bundle's unscoped package name.
- `lib/dispatch.js`: `ctx.subagents.start(config.provider, {label, prompt, parent: exec.agent,
  signal: exec.signal, persona, toolFilter: {allow}, agentOptions?, maxDepth})`; foreground only
  in the first cut; result formatted with `finalAssistantOutput`; model fallback surfaced in the
  result text, not only stderr. Apply-time capability guard: provider must advertise `persona` and
  `toolFilter`.
- `lib/index.js`: `inject: ['tools','subagents','systemPrompt']`; registers **one** tool
  `delegate_agent {agent_type: enum, prompt}`; a `systemPrompt.section` catalog of
  name + description; root watch with 300 ms debounce; exposes `ctx.moduleAgents.registerRoots(dirs,
  {rank})` for the marketplace plugin; re-registers on `subagent/provider-added/-removed`.
- `README.md`, `test/{catalog,dispatch,roots,corpus}.test.mjs`. Roster row in `plugins/README.md`;
  `dsh/profiles/web/plugins.json` row.

`agents/harnesses/dsh/plugins/packages/marketplace/` (second commit)
- `lib/catalog.js`: `listAgents` beside `listSkills`; agents no longer a Claude-only facet.
- `lib/agents.js`: `registerAgents(ctx, dirs)` → `ctx.get('moduleAgents')?.registerRoots(dirs,
  {rank: 700})`. `lib/registry.js`: `reconcileAgents` beside `reconcileSkills`.

`agents/harnesses/pi/extensions/module-agents.ts` (new, self-contained like `hook-runner.ts`)
- Discovery cloned from `hook-runner.ts:99-224`, retargeted at `modules/*/agents/*.md` in sibling,
  git-clone and npm-package sources; frontmatter via pi's own `parseFrontmatter`.
- `session_start`: filesystem discovery only, `pi.registerTool(delegate_agent)` left **inactive**
  (no `setActiveTools`). No awaited agent work in `session_start` (known deadlock).
- Activation: `before_agent_start` detects an injected `<skill name="<module>">` block for a module
  that ships agents and latches `setActiveTools([...active, 'delegate_agent'])` for the session;
  `/agents` command as the manual activator and catalog lister. Env guard
  `PI_MODULE_AGENT_CHILD=1` makes a child register nothing.
- Spawn: `node:child_process.spawn` of `pi --mode json -p --no-session -ne -ns -nc -na --model
  <route?> --tools <translated csv> --append-system-prompt <0600 tmpfile> "Task: ..."`; NDJSON
  `message_end`/`tool_result_end`; abort SIGTERM then SIGKILL after 5 s; **per-child timeout**
  (default 10 min) and concurrency cap (4 in flight) as new guards. Single `{agent_type, prompt}`
  schema; parallel fan-out is the model issuing several calls in one turn.
- `agents/harnesses/pi/test/module-agents.test.mjs`: discovery, argv construction, activation
  detection, corpus conformance. `wire.sh` needs no change (whole `extensions/` dir is linked).
- Gate: `pi/audit/measure.sh` shows 0 tokens/turn with the tool inactive; a second run with it
  active records the cost in `pi/README.md`, replacing the "no subagents, deliberately" section
  with the new stance.

### Marketplace repo

- `modules/feature-dev/{package.json, .claude-plugin/plugin.json, cordis.patch.yml (empty),
  README.md, LICENSE (MIT, Anthropic attribution)}`; root `marketplace.json` entry; all at 0.1.0.
- `skills/feature-dev/SKILL.md`: the 7-phase command ported to a skill. `$ARGUMENTS` kept.
  TodoWrite → "track phases as a todo list". Agent launches phrased as "dispatch
  `feature-dev:code-explorer`" with one line on each harness's dispatch surface (Claude Agent tool,
  pi/dsh `delegate_agent`) and the get-shit-done fallback line for a harness without the bridge.
- `agents/{code-explorer,code-architect,code-reviewer}.md`: verbatim from upstream.
- `agent-contract/README.md` + `fields.json`: author-facing contract, pointer to the harness-layer
  corpus, mirroring `hook-contract/README.md`.
- `bin/check.sh`: new step after the hooks-manifest step validating `modules/*/agents/*.md` against
  `agent-contract/fields.json` (name = filename, description present, tools split to known Claude
  names, model in {sonnet, haiku, opus, inherit}). Closes the local gap left by the skipped
  `claude plugin validate`.
- Regenerate `modules/index.yaml` and `pnpm-lock.yaml` (run `pnpm install`). Root `pi.skills`
  unchanged. Gate: `bin/check.sh`, `CHECK_BASE=origin/main bin/check.sh`, `claude plugin validate
  modules/feature-dev`, then `tests/smoke/{pi,dsh}.sh` against installed bridges.

## Build sequence

1. Harness layer: `agent-contract/` corpus + README.
2. Harness layer: `module-skills` roots generalization + tests.
3. Harness layer: `dsh-module-agents` + tests; install into `web` profile; call each agent once.
4. Harness layer: marketplace plugin `agents.js` commit.
5. Harness layer: `module-agents.ts` + tests; `pi/audit` measurement; README stance update.
6. Harness-layer PR merged and installed.
7. Marketplace: module, contract, `check.sh` step, regen; PR; smoke against installed bridges.

## Premortem items folded into the plan

Persona `{{` neutralization at build time; per-child timeout and concurrency cap on pi; foreground
only on dsh in the first cut (headless teardown kills in-process children); model fallback shown in
the result text; single dispatcher tool because provider tool-name rules forbid colons; activation
keyed on the injected skill block since `/name` commands bypass the `input` event; clone skew
between `~/.pi/agent/git` and the pinned tag surfaced by the `/agents` command listing each agent's
source path; official-plugin name collision documented in the module README.

## Open question for the maintainer

feature-dev is the heaviest fan-out shape in the marketplace (up to nine children per run) and pi's
default provider is still the local model that hung in the 2026-07-31 measurement. The caps above
bound the damage but do not make local orchestration good. Should the ported skill tell pi and dsh
sessions on a local provider to run explorer and reviewer passes sequentially, or is that left to
the user?

## Industry survey (2026-09-14) and why the approach holds

Surveyed against official docs: Claude Code, Codex CLI, Gemini CLI, Copilot, Cursor, OpenCode, Amp,
Kiro, Goose, Cline, Hermes, Crush, plus agentskills.io, agents.md, agent-plugins.org and the AAIF.

Standardized: `AGENTS.md` (AAIF), Agent Skills `SKILL.md` (40+ adopters; most also read
`.claude/skills`; `.agents/skills` is the neutral path), MCP (AAIF), and Agent Plugins v1.0
(agent-plugins.org; TSC from Amazon, Cursor, Microsoft, OpenAI, Vercel; adopters VS Code, Cursor,
Copilot, Codex, Kiro). Agent Plugins defines only `plugin.json` + `skills/` + `mcp.json`; it states
that agents, hooks, commands and rules are "too client-specific for a stable portable contract" and
belong in reverse-domain client extension dirs. Claude Code is not an adopter.

Not standardized: subagent definitions (markdown+frontmatter in Claude, Gemini, Cursor, Copilot,
OpenCode and Kiro; TOML in Codex; YAML recipes in Goose; code in Amp; none in Cline, Crush, pi, dsh).
The field set converges on `name`, `description`, `tools`/`mcp`, `model` and a prompt body. Cursor
reads `.claude/agents/*.md` directly. Hooks follow Claude's matcher/command/stdin/exit-2 shape
informally everywhere but no spec exists. Slash commands are being folded into skills by Claude,
Codex, Cursor, Amp and Kiro.

Consequences: (1) the repo's SKILL.md-first bet is the consensus; (2) an `agents/` contract with
markdown+frontmatter and the intersection fields is the plurality shape, so the bridge plan stands;
(3) adopting an Agent Plugins v1 `plugin.json` at each module root (Claude-specific fields stay in
`.claude-plugin/plugin.json`) would make every module installable in Cursor, Codex, Copilot, Kiro and
VS Code at the cost of one JSON file per module — a separate repo-shape PR, not part of this work.

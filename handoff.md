# Cross-harness agent-module marketplace — design and research record

**Date:** 2026-09-06 · **Status:** approved plan, pre-implementation · **Scope:** the technical layer only — what each harness supports, and how to build a public repo that holds `okf-wiki` and future modules natively on Claude Code, pi and dsh. The `okf-wiki` *feature* design is a separate brainstorm; §5 keeps the `llm-wiki` inventory as its pick-list.

Sources verified in this session: pi 0.84.1 as installed (`~/.nvm/versions/node/v24.15.0/lib/node_modules/@earendil-works/pi-coding-agent/{docs,dist}` — the tarball ships the version-correct docs), dsh as installed (`/usr/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/*`), Claude Code docs at code.claude.com (`skills`, `plugins`, `plugin-marketplaces`, `sub-agents`, `hooks`), `pnpm.io/package-sources`, `GoogleCloudPlatform/open-knowledge-format` (`SPEC.md` v0.2), the installed `llm-wiki` 0.2.0 plugin, and this repo's `agents/README.md` + `docs/superpowers/plans/2026-08-31-fleet-consolidation-analysis.md`.

---

## 1. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | The repo serves **both** native per-harness install and dotfiles integration, equal weight. | David: marketplace-style install "is the main functionality I want to bring across" all three. |
| D2 | **One repo = one marketplace of N modules** (`modules/<name>/`). | Matches Claude's marketplace, keeps per-module versions, and pi/dsh can each address it (§3.3). |
| D3 | **Commands are skills.** No `commands/` source dir; a user-invocable `SKILL.md` is the command. | `SKILL.md` is the only format all three read natively; Claude has merged commands into skills; dsh has no command files at all (§2.2). |
| D4 | Repo identity: **un-archive `allada-homelab/agent-harness-marketplace`** (private, archived 2026-09-01, holds the pre-fold `~/.agents` tree). Old tree deleted in the first commit; must be flipped **public**. | David's proposal. Org/public flip is David's action. |
| D5 | `okf-wiki` is **ambient-first** (background + agent-initiated), user-invoked second ⇒ it is a *code plugin* on every harness with skills as its invoked face. | Every ambient seam exists on all three (§2.4); "skill only" cannot run in the background. |
| D6 | `okf-wiki` feature design is **deferred** to its own brainstorm. | David: scope this to the technical layer; keep the llm-wiki inventory to pick from. |

---

## 2. What each harness supports

### 2.1 Roles of the primitives

**Skill** — a directory `skills/<name>/SKILL.md` (YAML frontmatter + body, freeform siblings `scripts/ references/ assets/`). Progressive disclosure: only `name` + `description` sit in the system prompt; the body is loaded when the model matches the description or the user invokes it. This is the Agent Skills open standard (agentskills.io) and all three harnesses implement it.

**Command / prompt template** — a `.md` file whose basename is a slash command; body is expanded with `$ARGUMENTS`-style substitution and sent as the user turn. Zero standing cost (nothing in the system prompt until invoked).

**Plugin / package / bundle** — the *distribution unit*: a directory (usually a git repo or npm package) with a manifest that tells the harness which skills, commands, extensions, hooks, agents it contributes. The word means something different on each harness (§2.3).

**Hook** — code that runs at a lifecycle event (prompt submitted, tool about to run, turn ended) and can inject context or deny the action.

**Subagent** — an isolated child agent with its own context, dispatched by the parent.

### 2.2 Per-harness detail

#### Claude Code

| Primitive | Facts |
|---|---|
| Skill | `~/.claude/skills/<n>/SKILL.md`, `.claude/skills/`, `<plugin>/skills/`, enterprise managed dir. Precedence enterprise > personal > project; plugin skills namespaced `/<plugin>:<skill>`. **"Custom commands have been merged into skills"** — `commands/deploy.md` and `skills/deploy/SKILL.md` both create `/deploy`; skills are recommended (code.claude.com/docs/en/skills). Frontmatter: `name description when_to_use argument-hint arguments disable-model-invocation user-invocable allowed-tools disallowed-tools model effort context: fork agent background hooks paths shell metadata license compatibility`. Body substitutions: `$ARGUMENTS`, `$N`/`$ARGUMENTS[N]`, `$name`, `${CLAUDE_SESSION_ID}`, `${CLAUDE_SKILL_DIR}`, `${CLAUDE_PROJECT_DIR}`, `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`; dynamic `` !`cmd` `` and ```` ```! ```` blocks. `skillOverrides` in settings (`on | name-only | user-invocable-only | off`) and `disableBundledSkills` hide skills **without editing files** — this is the exclude mechanism `agents/README.md:150` says Claude lacks; the rendered Claude view may be obsolete. |
| Command | `commands/*.md` = legacy flat skill; in a plugin, docs say "use `skills/` for new plugins". Frontmatter in practice `description argument-hint allowed-tools`. |
| Plugin | `<plugin>/.claude-plugin/plugin.json` (`name` = namespace, `description version author homepage repository license keywords`) — **optional** when components are in default dirs. Component dirs at plugin root: `skills/ commands/ agents/ hooks/hooks.json .mcp.json .lsp.json monitors/monitors.json bin/` (added to Bash PATH) `settings.json` (only `agent`, `subagentStatusLine`). Single-skill plugin may put `SKILL.md` at root. Dev loop: `claude --plugin-dir ./p`, `--plugin-url`, `/reload-plugins`, `claude plugin validate ./p [--strict]`, `claude plugin init <name>` (scaffolds a skills-dir plugin auto-loaded as `<name>@skills-dir`, no marketplace). Install state: `~/.claude/plugins/{known_marketplaces,installed_plugins}.json`, cache `~/.claude/plugins/cache/<marketplace>/<plugin>/<version-or-sha>/`; enablement is `enabledPlugins` in settings (`claude/settings.json:141-162`). |
| Marketplace | `.claude-plugin/marketplace.json` at repo root: `name`, `owner{name}`, `plugins[{name, source, version?, displayName?, license?, strict?, skills?/commands?/agents? paths}]`, `metadata.pluginRoot`, `renames`. `strict: false` ⇒ the entry *is* the whole definition. Sources: relative path, `{source: github, repo, ref?, sha?}`, `git`/`url`, `npm`, `archive` (+ `headers`), `command`. Add via `/plugin marketplace add owner/repo` or declaratively `extraKnownMarketplaces` + `enabledPlugins` in `.claude/settings.json`. |
| Agents | `~/.claude/agents/*.md`, `.claude/agents/`, `<plugin>/agents/`, `--agents`. Frontmatter `name description tools disallowedTools model permissionMode maxTurns skills memory isolation background effort color hooks`. Invoked by natural language, `@"name (agent)"`, `claude --agent`. |
| Hooks | Same `hooks` object shape in `~/.claude/settings.json`, project settings, managed policy, plugin `hooks/hooks.json`, skill/agent frontmatter. Events: `SessionStart SessionEnd UserPromptSubmit Stop StopFailure PreToolUse PostToolUse PostToolUseFailure PermissionRequest PermissionDenied SubagentStop PreCompact Notification FileChanged CwdChanged` + worktree events. Handler types: `command http mcp_tool prompt agent`. Contract: event JSON on stdin; exit 0 proceed, exit 2 block; stdout `hookSpecificOutput` (`additionalContext`, `permissionDecision`, rewritten input); `Stop` may return `{"decision":"block","reason"}` to force a follow-up. |
| Rules / output styles | `~/.claude/rules/*.md` (path-scoped via `paths:`), `~/.claude/output-styles/`. No plugin slot. Note skills now also carry `paths`, so a rule ≈ `user-invocable: false` skill with `paths`. |
| MCP | plugin `.mcp.json`; tools surface as `mcp__plugin_<plugin>_<server>__<tool>`. |

Prior art for a multi-harness plugin: `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.3.0/` ships **eight parallel manifests** over one content tree — `.claude-plugin/`, `.cursor-plugin/`, `.codex-plugin/`, `.kimi-plugin/`, `.devin-plugin/`, `.hermes-plugin/plugin.yaml`, `.opencode/plugins/*.js`, `.pi/extensions/*.ts`, `gemini-extension.json`.

#### pi 0.84.1

| Primitive | Facts |
|---|---|
| Skill | `docs/skills.md`; discovery `dist/core/package-manager.js:1955-2005`. Global: `~/.pi/agent/skills/`, **`~/.agents/skills/` hardcoded to `$HOME` (`:1968`)** — `PI_CODING_AGENT_DIR` does not move it. Project (behind `isProjectTrusted()`, `:1970`): `.pi/skills/`, and `.agents/skills` in cwd **and every ancestor to the git root** (`collectAncestorAgentsSkillDirs`, `:274-291`). Also packages, `settings.skills[]`, `--skill <path>`. Bare root `.md` files count as skills in `~/.pi/agent/skills`/`.pi/skills` but are **ignored** in `.agents/skills`. Frontmatter: `name` (req), `description` (req; missing ⇒ not loaded), `license compatibility metadata allowed-tools`(experimental) `disable-model-invocation`; unknown keys ignored; **does not require `name` == dirname**, explicitly because shared dirs. Invoked by description match or `/skill:<name> [args]` (`enableSkillCommands`). **Cost: name+description on every API request of the agentic loop** (measured here: one prompt → 9 requests × the block; dropping one bundled skill saved ~210 tok/turn, `pi/README.md`). |
| Prompt template | `docs/prompt-templates.md`. `~/.pi/agent/prompts/*.md`, `.pi/prompts/*.md` (trusted), package `prompts/`, `settings.prompts[]`, `--prompt-template`. **Non-recursive.** Frontmatter `description`, `argument-hint`. Substitution: `$1..$n`, `$@`/`$ARGUMENTS`, `${1:-default}`, `${@:-default}`, `${@:N}`, `${@:N:L}` — a **strict superset of Claude's**. Zero standing cost. Claude-only keys (`allowed-tools`, `model`) silently dropped. |
| Extension | `docs/extensions.md`. TypeScript via jiti, no build. `~/.pi/agent/extensions/{*.ts,*/index.ts}`, `.pi/extensions/` (trusted), packages, `settings.extensions[]`, `-e <path>`. API: `pi.on(event)`, `registerTool`, `registerCommand` (+ completions; duplicate names get `:1` suffix), `registerShortcut`, `registerFlag`, `registerProvider`, message/entry renderers, `appendEntry` (session JSONL), `sendMessage`/`sendUserMessage`, `setActiveTools`, `setModel`, `exec`, full TUI. Events: `project_trust resources_discover session_* before_agent_start agent_start/end/settled turn_start/end message_* tool_execution_* context before_provider_headers before_provider_request after_provider_response model_select thinking_level_select tool_call`(blocking) `tool_result`(mutating) `user_bash input`. Prompt-time precedence: extension commands → `input` → skill/template expansion → `before_agent_start` (`:275-300`). `resources_discover` lets an extension add skill/prompt/theme paths at runtime (`:369-387`). Cost: event-only extensions are 0 tok/turn; `registerTool` is not (one tool schema measured 331 tok/turn with UI). |
| Package (= pi's "plugin") | `docs/packages.md`. npm-style dir with `package.json`; either `"pi": {"extensions":[…],"skills":[…],"prompts":[…],"themes":[…]}` (root-relative globs, `!` exclusions) or convention dirs `extensions/ skills/ prompts/ themes/`. `keywords: ["pi-package"]` for the gallery. Sources: `npm:@scope/pkg@ver`, `git:host/user/repo@ref` (+ raw `https://`/`ssh://`), local paths (referenced in place). **Git installs the whole repo; no subpath.** Installed to `~/.pi/agent/{npm,git}/…`; `pi install|remove|list|update`. Can bundle: extensions, skills, prompts, themes, runtime `dependencies`. **Cannot** bundle MCP definitions, hooks-as-config, agents, settings — only as extension code. Consumer filtering: `settings.packages[{source, skills:[…], extensions:[…], …}]` — `[]` none, omit all, `!glob`/`+path`/`-path`; can only narrow. |
| Settings override grammar | `!pattern` glob-exclude, `+path` force-include, `-path` force-exclude, evaluated in that order (`isEnabledByOverrides`). A pattern is matched against rel path, basename, abs path, and for `SKILL.md` its parent dir — so a bare skill name works as an exclude. The same array is both extra-path list and override list. |
| Subagents | None (this repo removed the vendored extension 2026-08-11 for standing tool-schema cost). Escape hatch: `exec('pi -p …')`. |
| Trust | Project resources load only after trust; `defaultProjectTrust ask|always|never` governs `-p`/`--mode json|rpc`, which never prompt. This repo's `pi/trusted-projects.txt` → `~/.pi/agent/trust.json`. |

#### dsh

| Primitive | Facts |
|---|---|
| Skill | Provider `@deepseek-ai/dsh-skill-filesystem/lib/index.js` (plugin `skill-filesystem`, `inject: ["skills"]`). Roots in rank order (`roots()`, `:145-186`): `<projectRoot>/.dsh/skills` (100), `<projectRoot>/.agents/skills` (200), each `customSkillDirs` (300), `<dshHome>/skills` (400), `<agentsHome>/skills` (500, `agentsHome = config.agentsHome ?? $DSH_AGENTS_HOME ?? ~/.agents`, `resolve()`d — no `~` expansion, `:78`), optional `$DSH_BUNDLED_SKILL_DIR`. Roots are chokidar-watched and invalidated on first-party `edit`/`write` via `fs/observed`. Format: `<root>/<n>/SKILL.md` **or** flat `<root>/<n>.md`. Frontmatter honored: `name`, `description` (both required), `whenToUse`, `metadata`, `disable-model-invocation`, `user-invocable` (kebab only; camelCase legacy keys hard-rejected). **Silently dropped:** `allowed-tools`, `model`, `argument-hint`, `license`. Model side via the `skill` tool (`dsh-tool-skill`); user side gated by `invocation.userInvocable` + slash trigger UI. |
| Command | Registry `ctx.commands.register({name, description, input?, recordInput?, handler})` — a JS handler run against the agent without sending the command to the model. **No prompts/commands directory, no `.md` commands, no `$ARGUMENTS`.** Nearest native: a `user-invocable` skill. |
| Plugin (cordis) | ESM npm package exporting `{name, inject?, apply(ctx, config)}` + `package.json` `"dsh": {"bundle": {"patch": "./cordis.patch.yml"}}` (`dsh.client.platform: "web"` for a client bundle). The patch is a YAML array of loader-row ops (`- insert: [{id, name, config}]`, `- id/config/disabled`). Composition (`lib/profile-boot-*.js:156-200`): bundle layers in `dsh.profile.bundles` order → profile `cordis.patch.yml` → `$DSH_HOME/cordis.patch.yml` → `--patch` overlays. `ctx.*` seams: `tools.register`, events `tools/pre-execute` (waterfall allow/deny/ask) / `tools/post-execute`, `skills.registerProvider`, `commands.register`, `subagents`, `settings.mutate` (namespaced, optimistic concurrency), `authorization.registerFlow`, `systemPrompt.section` / `.context` / `.tools` / variables, `effect`, `logger` (**does not reach journald — use `process.stderr`**), `on('session/created' | 'session/event' | 'fs/observed' | 'turn/start' | 'turn/end' | 'agent/turn-stopping' | …)`, `cmdlineArgs`, `agentPresets`, `plan`, `jobs`, `mcp`. **Install:** `dsh plugin --profile <p> <pnpm args>` is a pnpm forwarder in the profile dir (`lib/plugin-*.js:100-125`); any pnpm spec works, incl. `github:` (hint printed about pnpm `allowBuilds` for git deps with `prepare`); afterwards `reconcilePlugins` re-derives `dsh.profile.bundles` from installed state. A plugin **cannot ship a skills dir or command markdown as files** — content needs a skill provider (this repo's `claude-bridge` is that shape). |
| Agent presets | `~/.dsh/.agent-presets/<id>/agent.cordis.yml`; shipped presets win duplicates (fork needs a new id); mounted once per preset, agents join by scope. This repo tracks deltas (`dsh/presets/*.yaml`). |
| Subagents | `ctx.subagents` provider registry + `dsh-tool-subagent` rows (`provider toolName agentOptions persona toolFilter maxDepth`=3, `backgroundMode: one-shot | continuable`). A "type" is a loader row, not a file. |
| Gaps vs Claude | no user-defined command files; no hooks-as-config; no markdown subagent definitions; no marketplace concept (plain pnpm); `allowed-tools` ignored. |

### 2.3 "Plugin" means three things

| | Claude | pi | dsh |
|---|---|---|---|
| Unit | content bundle + optional hooks/agents/MCP as data | content bundle + TS extensions | **code** bundle (loader rows); content only via a provider |
| Manifest | `.claude-plugin/plugin.json` (optional) | `package.json` `pi` key or convention dirs | `package.json` `dsh.bundle.patch` + `cordis.patch.yml` |
| Install | marketplace entry → per plugin | `pi install git:…` → **whole repo** | pnpm spec → per package, `#path:` subdir OK |
| Filter | `skillOverrides`, `enabledPlugins` | `settings.packages` object form | install only what you want |

The common denominator: **one content tree + a thin manifest per harness in the same directory** (the `superpowers` model).

### 2.4 Ambient seams

| Behavior | Claude | pi (extension) | dsh (plugin) |
|---|---|---|---|
| Inject context per prompt | `UserPromptSubmit` → `additionalContext` | `before_agent_start` — inject a message and/or rewrite `event.systemPrompt`; `systemPromptOptions` exposes loaded skills/context files (`docs/extensions.md:521-556`) | `ctx.systemPrompt.context({name, order, text: string \| (AssembleContext) => string})` — provider evaluated on every assembly (`dsh-system-prompt/lib/types/index.d.ts:71-78`) |
| Session-start preload | `SessionStart` | `session_start`; `resources_discover` for extra paths | `session/created`; static `systemPrompt.section` |
| Turn end | `Stop` — **can block** and force a follow-up | `agent_end` (may still retry/compact) / `agent_settled` (truly idle) — **fire only**; can `sendUserMessage` or `exec` | `turn/end {turn, reason}` — **fire only** (`dsh-session/lib/types/types.d.ts:241`); also `agent/turn-stopping` |
| Track edits | `PostToolUse Write\|Edit` | `tool_result`, `tool_execution_end` | `tools/post-execute`; native `fs/observed` |
| Gate a tool call | `PreToolUse` → `permissionDecision: deny` | `tool_call` (blocking; deny or rewrite) | `tools/pre-execute` waterfall → allow/deny/ask (`dsh-tools/lib/types/index.d.ts:38`) |
| Background worker | `background: true` agent + Agent tool | `exec('pi -p …')` detached | `ctx.subagents` one-shot / continuable |
| Isolated read (capsule) | `context: fork` + `agent:` | in-context read, or `pi -p` | `ctx.subagents` one-shot |
| Agent-initiated use | skill description match | skill description match | `description` + `whenToUse` |

Conclusions:
1. Every ambient behavior is reachable on all three. The one hard delta: **turn-end cannot block on pi/dsh** ⇒ capture runs *after* the turn in the background on all three (also removes llm-wiki's per-turn `Stop` latency on Claude).
2. Hooks are JSON on Claude and code on pi/dsh ⇒ **one engine + three thin adapters** over a shared stdin-JSON contract — the pattern this repo already runs for `agents/policy/{secrets,bash}.json` (Claude `redact-secret-output.py`, pi `secret-guard.ts`, dsh `dsh-secret-guard`) with `testcases.json` as the conformance corpus.
3. pi's per-request skill-description cost means every module skill must earn its description line; injected recall context must stay small (≤4 KB capsule, metadata-only candidate lists).

### 2.5 Install-path facts that fix the layout

- Claude installs **per module** via a marketplace entry with a relative `./modules/<n>` source; version in the entry gates updates.
- pi installs the **repo root** as one package (no git subpath, `docs/packages.md` §git) ⇒ the root `package.json` must carry a `pi` manifest globbing `modules/*/skills/**` and `modules/*/extensions/*.ts`; users narrow with `settings.packages` `!globs`.
- dsh installs **per module** with `github:owner/repo#vX&path:/modules/<n>` (pnpm `path:` fragment, `&`-combined with a ref — pnpm.io/package-sources). A module is a dsh plugin only if it has `dsh.bundle.patch`; content-only modules need the generic `dsh-module-skills` provider (§3.4).
- All three read `~/.agents/skills` natively ⇒ the fleet path is "symlink module `skills/` into the tree, re-render views".
- Frontmatter `harness:` / `tags:` (this repo's convention, `agents/README.md:130-139`) is ignored by all three ⇒ safe in a public repo.
- Absolute `~/.agents/lib/...` references (this repo's `lib/` convention) are **not** publishable; a portable skill references assets skill-relative.

---

## 3. Repo design — `allada-homelab/agent-harness-marketplace`

### 3.1 Layout

```
.claude-plugin/marketplace.json     # Claude: every module, source ./modules/<n>, version per entry
package.json                        # pi: the root IS the pi package
                                    #   "pi": {"skills": ["modules/*/skills/**"], "extensions": ["modules/*/extensions/*.ts"]}
                                    #   + pnpm workspace root for Node code
pnpm-workspace.yaml                 # packages: ["modules/*"]
modules/<name>/
  .claude-plugin/plugin.json        # {name, version, description}
  package.json                      # {"name": "@allada-homelab/<n>", "version", "pi": {…},
                                    #  "dsh": {"bundle": {"patch": "./cordis.patch.yml"}}}   (dsh key only for code modules)
  cordis.patch.yml                  # dsh loader rows; content-only modules insert one dsh-module-skills row
  skills/<skill>/SKILL.md           # THE shared content — commands are skills
  extensions/<n>.ts                 # pi adapter (optional)
  hooks/hooks.json                  # Claude adapter (optional)
  lib/index.js                      # dsh adapter (optional)
  <engine>/                         # shared engine (Python or JS) the three adapters call
  test/  README.md
modules/dsh-module-skills/          # generic dsh bridge — the one required code module
bin/check.sh                        # portability lint (§3.2), manifest/version agreement
bin/render-index.py                 # generates modules/index.yaml from harness:/tags: (port of agents/bin/agents-index.py)
docs/{authoring,install-claude,install-pi,install-dsh,portability}.md
.github/workflows/ci.yml            # lint + version agreement + Node/Python tests
```

### 3.2 Portable `SKILL.md` contract (enforced by `bin/check.sh`)

- Required: `name` (== directory name — Claude requires it; pi/dsh tolerate), `description` (one tight sentence; pi pays for it on every request).
- Allowed: `argument-hint`, `user-invocable`, `disable-model-invocation`, `license`, `compatibility`, `metadata`, `harness: [claude|pi|dsh]`, `tags: […]`.
- **Selection guidance lives in `description`.** `whenToUse`/`when_to_use` are not honored by dsh's catalog (A11: parsed and shipped over the API, but `dsh-tool-skill` emits name+description only and the UI never renders it), so neither may carry anything the `description` lacks. `bin/lint-skills.py` warns when it does.
- **Directory-bundle form only** — `<root>/<name>/SKILL.md`, never a flat `<root>/<name>.md`: dsh accepts the flat form and then hands it the ROOT as its `resourceBase` (A18), so `./scripts/x.py` resolves into the directory shared with every sibling. `bin/lint-skills.py` rejects it.
- A command = `user-invocable: true` (+ `disable-model-invocation: true` for pure commands) + `argument-hint`. Claude: `/name`; pi: `/skill:name`; dsh: user-invocable skill (bare `/name` via the bridge, §3.4).
- Substitutions: `$ARGUMENTS`, `$N` only — and **on dsh they are passed through literally** until the `dsh-module-skills` bridge exists (A12; §8.1 dsh-2). A portable body must read correctly with the token unexpanded and the user's text following as prose; `bin/lint-skills.py` warns on an unacknowledged one.
- Forbidden in a portable skill: `context: fork`, `agent:`, `hooks:`, `effort:`, `model:`, `allowed-tools:` (dsh drops it — a tool restriction that silently vanishes is worse than none), `${CLAUDE_*}`, absolute paths, `` !`cmd` `` injection. Harness-specific behavior goes in a sibling skill scoped with `harness:`.
- Assets referenced skill-relative (`./scripts/x.py`), never via a tree path.

### 3.3 Install contract

| Harness | Install | Update | Filter |
|---|---|---|---|
| Claude | `/plugin marketplace add allada-homelab/agent-harness-marketplace` → `/plugin install <n>@agent-harness-marketplace` | bump entry version | `skillOverrides` |
| pi | `pi install git:github.com/allada-homelab/agent-harness-marketplace@vX.Y.Z` | `pi install …@vNext` | `settings.packages[{source, skills: ["!modules/<n>/**"], extensions: […]}]` |
| dsh | `dsh plugin --profile <p> add "github:allada-homelab/agent-harness-marketplace#vX.Y.Z&path:/modules/dsh-module-skills"` once, then `…&path:/modules/<n>` per module | re-add at the new ref | install only wanted modules |

Versioning: repo git tags `vX.Y.Z` are the pi/dsh ref; each module's version lives in `plugin.json`, `package.json` and its marketplace entry, bumped when the module changes; CI asserts the three agree.

### 3.4 `dsh-module-skills` bridge

Cordis plugin, `inject: ['skills']`:
1. Resolve module roots: `config.dirs` (absolute; the fleet/dotfiles path) ∪ auto-discovery (read the profile's `package.json` `dsh.profile.bundles`, `createRequire`-resolve each, keep those with a `skills/` dir). Dedupe by realpath.
2. `ctx.skills.registerProvider` per root — discovery/parse borrowed from `agents/harnesses/dsh/plugins/packages/claude-bridge/lib/index.js` (skills-only; no `spawn`, no trust gate, since nothing executes).
3. Skills with `user-invocable: true` + `disable-model-invocation: true` also get `ctx.commands.register` with `$ARGUMENTS`/`$N` expansion — the only place command semantics need code on dsh.
4. Warnings to `process.stderr`; fails open and loud.

Each content module's `cordis.patch.yml` inserts one row of this plugin, so `reconcilePlugins` picks the module up. Rejected: patching `skill-filesystem.customSkillDirs` per module — needs an absolute path unknown at authoring time.

### 3.5 Dotfiles integration (this repo)

- `agents/modules.tsv`: `repo  ref  module  enabled` (TSV, every field non-empty, `-` for none — same discipline as `bootstrap/steps.tsv`).
- `setup_agents_tree` (`scripts/common.sh`) clones/fetches each repo into `~/.cache/dotfiles/agent-modules/<repo>@<ref>` and symlinks `modules/<m>/skills/*` into `~/.agents/skills/` (name collision with a local skill = error, never shadow). `render-agent-views.py` then filters by `harness:`/`tags:` unchanged; profiles keep `agents-exclude-tags.conf`.
- Adapters: pi `.ts` wired by `agents/harnesses/wire.sh --pi`; dsh plugins by the existing `dsh-plugins-sync.py` — only for modules the fleet enables. The dsh bridge is unnecessary on the fleet path (skills arrive through the tree).
- Guard: `tests/test_agent_views.sh` gains a fixture module repo.

### 3.6 Migration

- `agent-harness-marketplace`'s current tree (pre-fold `~/.agents`) is deleted in the first commit — it lives in this repo's `agents/` since 2026-09-01. README rewritten for consumers.
- `public-skills`: `minimalist-code-review` → module as-is; `get-shit-done` → portable skills module + `harness: [claude]` sibling keeping its hooks (open decision); `llm-wiki` stays and is superseded by `okf-wiki`.
- This repo's `agents/skills` (4) and `dual-agent-pr-review` migrate only where `tags:` allows; `agents/policy/` stays private pending a homelab-content audit.

---

## 4. OKF v0.2 — what the spec fixes and what it leaves to us

Repo: `GoogleCloudPlatform/open-knowledge-format` (Apache-2.0, initial commit 2026-08-14, pushed 2026-08-21, no tags/releases/CI). Everything normative is `SPEC.md` v0.2.

**Fixed by the spec**
- Bundle = directory tree of `.md`; concept ID = bundle-relative path minus `.md`; layout is domain-free.
- Reserved files: `index.md` (per directory; `# Section` headings with `* [Title](url) - description` bullets, descriptions from target frontmatter; root may carry `okf_version`) and `log.md` (`## YYYY-MM-DD` newest-first; bold-verb bullets are convention). No other frontmatter on reserved files.
- Frontmatter: `type` is the **only** required key (free-form; consumers MUST tolerate unknown types). Recommended `title description resource tags`. Provenance families: `sources: [{id, resource (req), title, author, usage_count, last_modified}]` + `usage_window`, per-claim attribution by **footnotes keyed to `sources[].id`**; `generated: {by (req), at}`; `verified: [{by, at}]` (bare mapping = one-element list); `status: draft|stable|deprecated` (absent ⇒ stable); `stale_after` absolute ISO-8601 with offset. Actor convention `<producer>/<version> | human:<id> | process:<id>`. **Trust tiers are derived, never stored**: no `verified` ⇒ unverified; only non-`human:` ⇒ machine-confirmed; any `human:` ⇒ human-reviewed. No credibility score.
- Links: plain markdown; **bundle-absolute `/path.md` recommended**, relative allowed; untyped edges; consumers MUST tolerate broken links. (Upstream contradiction: the reference agent emits file-relative links "because `/` breaks GitHub rendering" — issue #14 open.)
- §10 Attested Computations: a computation is its own concept (`type: Attested Computation`, `runtime`, `parameters`, inline `# Computation` or `computation:` path, `executor`, `attester`); the agent supplies parameter values only and MUST NOT edit the computation; receipts/verdicts never stored in-bundle. §12 declares the runtime protocol, attester ABI and caching **unstable/deferred**.
- §11 conformance is permissive: parseable frontmatter + non-empty `type` + reserved files per §8/§9; MUST NOT reject for missing optional fields, unknown keys, broken links, missing `index.md`.

**Left to us** — no workflow vocabulary (capture/query/ingest/tend are llm-wiki's words), no validator, no JSON schema (issue #8), no skill/agent extension, no MCP server. Shipped tooling is a Python/ADK/Gemini reference agent (`enrich`, `visualize`), a Cytoscape viewer, an example SQL-equality attester, four example bundles.

**Named best practices / anti-patterns** — bundle-absolute links; structural markdown over prose; one-sentence `description` (index generators use it verbatim); keyed footnotes over positional; one Attested Computation per figure; signals not scores; honest `human:` prefixes; bundles in git. Don't: let the agent author/rewrite a computation or string-interpolate parameters; store scores or receipts; reject on unknowns; use v0.1 `timestamp` / `# Citations`.

**Open upstream issues to watch:** #16 typed relationships, #15 `imported`, #14 link resolution, #13 `refuted`, #11 tombstones, #9 `[[wiki]]` links, #8 JSON Schema.

---

## 5. `llm-wiki` 0.2.0 inventory — the pick-list for `okf-wiki`

Installed at `~/.claude/plugins/cache/public-skills/llm-wiki/0.2.0/`; ~11.1k lines; Python 3 stdlib only; all model surfaces `model: sonnet`.

### 5.1 Invoked workflows (`commands/*.md`)

| Command | What it does |
|---|---|
| `capture` (114) | Resolve bundle (`--bundle` → `<project>/llm-wiki` → walk up) → create vs update by slug/title/`resource` → placement via `topology.py select` (never invents a section) → compose from `references/concept-template.md` → write to `mktemp` → `bundle_ops.py apply` (staging mirror, index regen, log append, strict Doctor, secret scan, commit, v0.1→v0.2 migration) → `applied | blocked:doctor | blocked:secret | error:post-commit` → one breadcrumb. |
| `query` (71) | Answer mode: invoke the route skill named in the UserPromptSubmit `candidate_envelope` (`recall-glimmer` / `recall` / `recall-archaeologist`) inside an untrusted-data boundary; render the ≤4 KB `context_capsule`; relay `VERIFY:`/`GAP:`; optionally dispatch ≤1 `wiki-verifier` per cited concept. Browse mode: walk `index.md`. Never writes. |
| `ingest` (67) | `ingest_plan.py plan` → ≤3 `wiki-explorer` agents in parallel → accept only matching `evidence_packet`s → dedupe, cap 4/15/40 → `--dry-run` or `batch_publication.py` + `bundle_ops batch-apply` → `ingest_plan.py finish`. |
| `tend` (58) | Read-only digest: `doctor.py --mode strict` (R1–R3/R8 errors; R4 broken link, R5 type vocab, R9 legacy warnings) → orphans/near-dupes/missing links → staleness (`generated.at`, log recency, `stale_after`, `status`) → `## Verify` anchor freshness via `git log --since=<verified.at> -- <anchor-file>` → prioritized digest. |
| `prune` (49) | Report inbound links (never rewritten) → mirror → `bundle_ops remove` → `rmdir` empties → index → log → Doctor → replay on the real bundle. |
| `reorganize` (70) | Plan moves → baseline `linkcheck` + Doctor → mirror → `bundle_ops move` (rewrites inbound links in `./` and `/` forms) → index/log → Doctor + link-health diff (`after ⊆ before`) → `secret_scan.py` on changed files → replay. |
| `resolve` (49) | `bundle_ops.py merge` under the bundle lock: union-merge `log.md`, regenerate conflicted `index.md`, re-Doctor. Concept conflicts out of scope. |

### 5.2 Knowledge and agents

- `skills/wiki/SKILL.md` (202): secrets prohibition, OKF mental model (path = identity), wiki-vs-CLAUDE.md placement, R1/R2/R3 authoring rules, flat-first nesting, Doctor as authority, permissive reading, trust-but-verify with untrusted-data delimiters, the always-on loop (read first → fork capsule → Scribe → publication → impact → gaps → quiet breadcrumbs), `## Verify` anchors, relative-link rule. References: `capture-triggers concept-template frontmatter ingestion linking reserved-files`.
- `recall`, `recall-glimmer`, `recall-archaeologist`: 13–16-line shims, `context: fork` + `agent:`.
- Agents (9): `wiki-glimmer` (Read; low; 4 turns), `wiki-compiler` (Read+Agent; medium; 10; 2-worker fan-out; `insufficient_evidence` + `gap_proposals`), `wiki-archaeologist` (high; 24; 3 workers), `wiki-evidence-worker` (one allowlisted scope → ≤3 KB packet), `wiki-explorer` (ingest proposals from an exact manifest), `wiki-capturer` = Scribe (Read/Bash/Write; **background**; runs the fixed `publication.py` → `bundle_ops apply` pipeline), `wiki-sentinel` (**background**; change-impact), `wiki-researcher` (**background**; gap research, quarantine unless objective code+test), `wiki-verifier` (one anchor → confirmed/stale/couldn't-verify; `run:` anchors disabled).

### 5.3 Hooks (`hooks/hooks.json`, 9 entries)

| Event | Script | Behavior |
|---|---|---|
| SessionStart | `hook_session_start.py` | sweep stale capture markers; detect vanished bundle; inject bounded metadata-only catalog + `CONSULT_GUIDANCE`; init evidence ledger |
| UserPromptSubmit | `hook_user_prompt.py` | skip if no bundle / outside project / `autonomy: off` / prompt from an `llm-wiki:` agent; rank candidates (`catalog.py`), pick route (`routing.py`), plan fan-out, issue a controller job with per-route budgets (glimmer 2 calls/24 turns/240 s; oracle 5/36/360; archaeologist 6/42/420); inject `candidate_envelope` |
| PreToolUse `Write\|Edit` | `hook_pre_write.py` | secret scan (fails closed) then `doctor.check_concept` for writes inside the bundle → `permissionDecision: deny`; Scribe writes restricted to `/tmp` staging |
| PreToolUse `Read\|Grep\|Glob` | `hook_pre_read.py` | path policy for read-only agents: deny out-of-project, credential stores, `sensitive_paths`, unbounded globs, off-manifest paths |
| PreToolUse `Bash` | `hook_pre_bash.py` | Scribe may run only literal `publication.py` / `bundle_ops.py apply` |
| PreToolUse `Agent\|Skill` | `hook_pre_dispatch.py` | deny protected dispatch without a startable controller job |
| PostToolUse `Write\|Edit` | `hook_post_tool.py` | edit outside bundle ⇒ bump `capture-pending-<session>` marker |
| PostToolUse `Agent\|Skill` | `hook_post_dispatch.py` | complete jobs; on `insufficient_evidence` dedupe the gap, build a safe manifest, emit researcher dispatch |
| Stop | `hook_stop.py` | finalize evidence packet; if capture marker ≥ `capture_min_edits`, prepare Sentinel + Scribe requests and return `{"decision":"block"}` forcing one parallel fire-and-forget dispatch |

### 5.4 Engines (`scripts/`, Python stdlib)

`bundle_ops.py` 1354 (`index log-append move remove apply batch-apply stage linkcheck merge`; bundle lock; legacy migration; `generated` stamping) · `doctor.py` 791 (OKF v0.2 validator R1–R9, strict/lenient, exit 0/1/2; **stricter than spec**: R5 canonical-type warning) · `secret_scan.py` 208 (named-key regexes + entropy; `# pragma: allowlist secret`) · `publication.py` 185 (HEAD/source-hash preflight; exit 3 `stale-result`) · `batch_publication.py` 190 · `ingest_plan.py` 117 · `topology.py` 187 · libraries `catalog.py` 225, `routing.py` 84, `fanout.py` 34, `impact.py` 130, `gap.py` 250, `job_state.py` 436 (causal run/job IDs, budgets, cooldowns, kill switches), `evidence_ledger.py` 272, `packet_contracts.py` 462, `provenance.py` 211, `dispatch.py` 97, `trust_boundary.py` 18, `_hook_common.py` 225. Config: `<project>/.claude/llm-wiki.local.md` frontmatter (`capture_nudge capture_min_edits sensitive_paths autonomy autonomy_* cooldowns`). State: gitignored `llm-wiki/.llm-wiki/`.

### 5.5 Format as implemented vs spec

Path-is-identity; `type` required; `generated` code-stamped only; `verified` scalar-or-list; `sources` + keyed footnotes; `status`, `stale_after` (date, not instant); actor convention Doctor-enforced. **Deviations/extensions:** relative-only links (bundle-absolute rejected for GitHub rendering); `## Verify` anchor (free text `file:symbol`, repo-root-relative, no `run:`), `## Related` section; engine-generated `index.md`/`log.md` never hand-edited; v0.1→v0.2 auto-migration inside `apply`.

### 5.6 Portability classification

| Feature | Class |
|---|---|
| OKF doctrine skill; `capture prune reorganize resolve tend`; `query` browse | **portable** (instructions + scripts; only `${CLAUDE_PLUGIN_ROOT}` to replace) |
| recall routes / capsule isolation; parallel ingest explorers; verifier | needs subagent (dsh native; pi `pi -p`; else in-context) |
| recall injection; session catalog; write/read/bash/dispatch gates; capture marker + Stop scheduling; background Scribe/Sentinel/Researcher | needs hooks — all have native seams on pi/dsh (§2.4); Stop-block becomes post-turn |

Tests: 20 deterministic modules (~2.6k lines) — hook I/O, packet contracts, Doctor/migration, publication, job controller, ledger, gap policy, provenance, topology, routing corpus, malicious-evidence fixture. **No model-in-the-loop evals** — no baseline for capsule quality or capture precision.

### 5.7 Simplification candidates (David: "simpler if possible")

The job controller (budgets, cooldowns, kill switches), evidence ledger, packet contracts, three recall routes and the dispatch job gate all exist to police Claude subagents dispatched through prompts. A post-turn background Scribe on native seams (`ctx.subagents` / `pi -p` / Claude background agent) with a single publication gate may not need any of them. Keep: the publication gate (doctor + secret scan + provenance + index/log + commit), untrusted-data delimiters, `## Verify` + git-freshness `tend`, the deterministic test corpus. Decide in the okf-wiki brainstorm.

---

## 6. Phases and verification

1. **Un-archive + reset** (David flips public): delete old tree, scaffold §3.1, root pi manifest, `marketplace.json`, `bin/check.sh`, CI. First content module: `minimalist-code-review`.
2. **`dsh-module-skills`**: unit tests (parser, provider dedupe, `$ARGUMENTS` expansion) + live check — `dsh plugin … add`, `dsh --dump-config` shows the row, skill appears in the catalog.
3. **Native-install E2E** on this machine, all three harnesses; the exact commands + outputs recorded in `docs/install-*.md`.
4. **Dotfiles integration**: `agents/modules.tsv`, `setup_agents_tree` clone+link, fixture test; `bootstrap sync` shows the module skill in all three views.
5. **`okf-wiki` design brainstorm** (own session; §5 as pick-list, §2.4 as seam map) → first code module.

Gates: `bin/check.sh` green and a deliberately non-portable fixture fails it; version-agreement test fails on divergence; each harness lists the same skill from a fresh install (cite command + output); `render-agent-views.py` emits the module skill in each view and `tests/test_agent_views.sh` passes; CI grep finds no `~/.agents/lib`, homelab hosts or absolute paths.

## 7. Open decisions

1. Keep the `allada-homelab` org for the public repo (recommended, David's call — must become public) vs a `davidallada/` repo.
2. `get-shit-done`: split portable/claude-only (recommended) vs defer.
3. Whether Claude's `skillOverrides` retires the rendered Claude view in `render-agent-views.py` (context-cost rationale in `agents/README.md:154-157` still applies to pi, not Claude).

---

## 8. Foundation work on the harnesses themselves

David's question (2026-09-06): should any *base-level* part of pi or dsh be added, fixed or refactored so the marketplace and `okf-wiki` stand on solid ground, rather than on a thin patch? Assessment per harness, ranked by how load-bearing the gap is.

### 8.1 dsh — three real base gaps, one fragility

| # | Gap | Today | Proposed base work | Load-bearing for |
|---|---|---|---|---|
| dsh-1 | **No file-based skill contribution from a package.** A plugin cannot ship `skills/`; content needs a provider. | `claude-bridge` (2.1k lines) does it for a *repo's* `.claude/` tree only, with hook spawning and a trust gate — Claude-specific, not a base. | `dsh-module-skills` (§3.4) built as the **generic base**: any configured root or any installed bundle with `skills/` becomes a provider. `claude-bridge` can later delegate its skills half to it. | every content module |
| dsh-2 | **No `/name` slash commands from files, and no `$ARGUMENTS` at all** — CONFIRMED 2026-09-06 (A12): the UI's `/name` types into the composer and the server injects the SKILL.md body verbatim, so the user's text stays outside it. | none — until the bridge exists, a `$ARGUMENTS`/`$N` token in a dsh-visible body is passed through **literally**, and `agents/bin/lint-skills.py` warns on an unacknowledged one. | same plugin: `ctx.commands.register` for `user-invocable: true` skills, `$ARGUMENTS`/`$N` expansion. Verify first whether the native trigger already passes args (scout open Q6) — if it does, register only what is missing. | D3 (commands are skills) |
| dsh-3 | **No hooks-as-config.** Every ambient behavior is plugin JS. | fleet guards are hand-written plugins over `policy/*.json`. | **`dsh-hook-runner`**: reads a Claude-shaped `hooks.json` and maps events — `PreToolUse`→`tools/pre-execute` (deny/rewrite), `PostToolUse`→`tools/post-execute`, `UserPromptSubmit`→`systemPrompt.context` provider, `SessionStart`→`session/created`, `Stop`→`turn/end` + `agent/turn-stopping` (`agent.steer()` makes refusal real on dsh, per `agents/README.md` 2026-09-02 correction). Same stdin-JSON / exit-2 / stdout-JSON contract. Fails open and loud to `process.stderr`. | every ambient module — see §8.4 |
| dsh-4 | `agentsHome` is absent on shipped preset rows, and on `web` the profile's own row is DISABLED by `dsh-web-app` (A6) — so the patch layer filters nothing there. | `scripts/dsh-run.sh` exports `$DSH_AGENTS_HOME`, and `scripts/dsh-presets-render.py` injects `config.agentsHome` onto each rendered preset's own row; `bootstrap verify` grades both. | Keep; document as a known upstream fragility. Not base work. | fleet only |
| dsh-5 | Subagent API from a plugin (`ctx.subagents` one-shot) is un-exercised by us. | `dsh-tool-subagent` rows exist; no plugin here calls the provider API. | Spike in the okf-wiki phase: one-shot child from a plugin, capture its result. Needed before designing background capture. | okf-wiki |

Also fixed as doctrine, not code: dsh plugin logs go to `process.stderr`; `allowed-tools` is silently dropped, so the portable contract forbids relying on it (§3.2).

### 8.2 pi — one parity nicety, one base runner, one spike

| # | Gap | Today | Proposed base work | Load-bearing for |
|---|---|---|---|---|
| pi-1 | User-invocable skills are `/skill:name`, not `/name`. | works, just differently named | `skill-commands.ts` (~40 lines): `registerCommand(name)` per `user-invocable` skill, forwarding args. Optional parity; measure it (`pi/audit/measure.sh`) — `registerCommand` is not `registerTool`, expected 0 tok/turn. | D3 ergonomics |
| pi-2 | **No hooks-as-config.** | fleet guards are hand-written `.ts` over `policy/*.json`. | **`hook-runner.ts`**: same manifest as dsh-3; `PreToolUse`→`tool_call`, `PostToolUse`→`tool_result`, `UserPromptSubmit`→`before_agent_start` (inject message / system prompt), `SessionStart`→`session_start`, `Stop`→`agent_settled` (observe-only; runner may `sendUserMessage` for a follow-up). Event-only ⇒ 0 tok/turn standing cost. | every ambient module |
| pi-3 | No subagents. | `exec('pi -p …')` | Spike alongside dsh-5: detached `pi -p` from `agent_settled`, result via `appendEntry`. | okf-wiki |
| pi-4 | Project-scope skills need repo trust; headless `-p` never prompts. | `pi/trusted-projects.txt` for the fleet | Docs only for third parties (`install-pi.md`): user scope is always trusted, so installing the marketplace globally avoids it. | — |
| pi-5 | Git install is whole-repo. | fine with the root manifest | Optional upstream PR to `earendil-works/pi-coding-agent` for a `#path:` subdir — nice-to-have, not blocking. | — |

### 8.3 Claude — nothing base-level

`hooks.json` with `${CLAUDE_PLUGIN_ROOT}` already is the manifest. Open item only: whether `skillOverrides` retires the rendered Claude view (§7.3).

### 8.4 The fork: generic hook runners vs per-module adapters

**Prior decision (2026-09-02, `agents/README.md` §Hooks):** runners not written; the two fleet guards became native extensions/plugins over shared data. Rationale then: only two consumers, both turn-level, and native code was cleaner than a runner for two rows.

**What changed:** the marketplace makes hooks a *product surface*. A third party installing `okf-wiki` on dsh or pi gets its ambient behavior only if either (a) the module ships a hand-written adapter per harness, or (b) a runner turns the module's one `hooks.json` into behavior everywhere.

| | (a) per-module adapters (`extensions/<n>.ts`, `lib/index.js`) | (b) generic runners (`hook-runner.ts`, `dsh-hook-runner`) |
|---|---|---|
| Per-module cost | 100–200 lines × 2 per ambient module, each re-implementing event mapping | 0 — `hooks.json` + scripts |
| Base cost | none | ~150–300 lines each + a conformance corpus (event fixtures → expected decision), once |
| Fidelity | can use harness-native features (dsh `ctx.subagents`, pi `sendUserMessage`) | limited to the Claude contract; native extras still possible in an optional adapter |
| Risk | adapter drift between modules (the same drift `policy/testcases.json` exists to stop) | runner bugs affect every module at once — mitigated by the corpus |
| Rollback | n/a | delete the runner; modules keep working on Claude |

**Recommendation: (b), with (a) allowed as an optional escape hatch.** The runners are the two pieces of base work that make "ambient module = data on all three harnesses" true; without them every ambient module is three implementations, which is the drift class this repo has already paid for twice. Turn-level semantics are documented as degraded on pi (observe + follow-up message) and effective on dsh (`agent.steer()`); tool-level and prompt-level port at full strength. The runners live in the marketplace as modules (`hook-runner-pi`, `hook-runner-dsh`), installed once like `dsh-module-skills`.

### 8.5 Where it lands in the phases

- **Phase 2 (renamed "foundation")**: `dsh-module-skills` (dsh-1, dsh-2), `hook-runner-pi` (pi-2), `hook-runner-dsh` (dsh-3), `skill-commands.ts` (pi-1) — each with unit tests, the shared hook conformance corpus, and a live check against the running harness.
- **Phase 5 pre-work**: the subagent spikes (dsh-5, pi-3) before the okf-wiki brainstorm, so its design rests on measured behavior.

---

## 9. Feature ledger, ranked most → least foundational

Status legend: **native** = harness does it out of the box · **ours** = a plugin/extension/patch in this repo fills it · **partial** = exists but incomplete · **missing** = nothing today. Rank weighs (a) how much else stands on it, (b) what the marketplace needs. Tiers: **T1** load-bearing for the marketplace, **T2** foundation for ambient modules (okf-wiki), **T3** operational, audited but not blocking, **T4** peripheral.

### 9.1 pi 0.84.1

| # | Tier | Feature | Status | Where / gap |
|---|---|---|---|---|
| 1 | T1 | Skills from `~/.agents/skills` + project `.agents/skills` | native (+ ours for trust) | `package-manager.js:1955-2005`; project scope needs `pi/trusted-projects.txt` → `trust.json` (the `PYTRUST` block in `agents/harnesses/wire.sh`) |
| 2 | T1 | Package contributes skills / prompts / extensions / themes | native | pi package format, `pi install git:…` |
| 3 | T1 | Skill filtering per harness/profile | ours | `render-agent-views.py` → `!glob` excludes in `pi/settings.local.<env>.json` |
| 4 | T1 | Tool-call gate (deny / rewrite) | native event, ours consumers | `tool_call` → `bash-guard.ts`, `secret-guard.ts`, `shell-guard.ts`, `push-branch-guard.ts` over `agents/policy/*.json` + conformance corpus |
| 5 | T1 | Hooks as config (`hooks.json`) | **missing** | proposed `hook-runner.ts` (§8.2 pi-2) |
| 6 | T1 | Install one module from a multi-module repo | partial | whole-repo only; narrow via `settings.packages` object form |
| 7 | T1 | User-invocable skill as `/name` | **missing** | `/skill:name` today; proposed `skill-commands.ts` (§8.2 pi-1) |
| 8 | T2 | Per-prompt context injection | native event, ours consumer | `before_agent_start` → `conditional-doctrine.ts` |
| 9 | T2 | Session-start preload / `resources_discover` | native | no consumer of ours yet |
| 10 | T2 | Turn-end trigger | partial | `agent_end`/`agent_settled` fire-only; `push-branch-guard.ts` uses as annotation |
| 11 | T2 | Subagents / background workers | **missing** | removed 2026-08; `exec('pi -p')` — spike pending (§8.2 pi-3) |
| 12 | T2 | Output redaction | ours | `secret-guard.ts` on `tool_result` |
| 13 | T2 | File-based slash commands (prompt templates) | native (+ ours wiring) | `wire.sh --pi` symlinks the commands view to `~/.pi/agent/prompts`; superseded by D3 |
| 14 | T3 | MCP servers | third-party + ours | `pi-mcp-adapter@2.23.0`, `mcp-registration.ts`, shared `~/.config/mcp/mcp.json` |
| 15 | T3 | Durable session state (`/goal /todo /constraint`) | ours | `session-state.ts` |
| 16 | T3 | Default bash timeout | ours | `bash-timeout.ts` |
| 17 | T3 | Ask-user question tool | ours | `questionnaire.ts` (331 tok/turn with UI) |
| 18 | T3 | Timers / polling | ours | `timers.ts` |
| 19 | T3 | Sandbox / permissions | missing in pi; ours inert | `srt` wrapper in `40-lazy.zsh`, boundary unproven |
| 20 | T4 | Hash-anchored edit, tool repair, statusline, compact transcript | third-party pins | `pi/settings.json` |
| 21 | T4 | Module catalog / listing | partial | per-package install/update only |

### 9.2 dsh

| # | Tier | Feature | Status | Where / gap |
|---|---|---|---|---|
| 1 | T1 | Skills from `~/.agents/skills` + project `.agents/skills` | native | `dsh-skill-filesystem`, ranked roots, watched |
| 2 | T1 | Skill filtering per harness/profile | ours, partial | `DSH_AGENTS_HOME` from `scripts/dsh-run.sh` + patch-layer `agentsHome`; two levers because preset rows lack `agentsHome` |
| 3 | T1 | Plugin bundles code (tools, gates, providers, UI) | native | cordis `dsh.bundle.patch`; `dsh plugin add <pnpm spec>` |
| 4 | T1 | Install one module from a multi-module repo | native | pnpm `github:o/r#ref&path:/modules/x` |
| 5 | T1 | Package contributes skills as files | **missing** generically; ours partial | `claude-bridge` (repo `.claude/` only, Claude-specific); proposed `dsh-module-skills` (§8.1 dsh-1) |
| 6 | T1 | Tool-call gate | native waterfall, ours consumers | `tools/pre-execute` → `bash-guard`, `secret-guard`, `goal-round-guard` |
| 7 | T1 | Hooks as config (`hooks.json`) | **missing** generically; ours partial | `claude-bridge` runs a repo's SessionStart/PreToolUse scripts behind `trustedRoots`; proposed `dsh-hook-runner` (§8.1 dsh-3) |
| 8 | T1 | File-based slash commands / `/name` with args | **missing** / partial | JS-only `ctx.commands`; slash-trigger UI for `user-invocable` skills, `$ARGUMENTS` passthrough unverified (§8.1 dsh-2) |
| 9 | T2 | Per-prompt context injection | native | `systemPrompt.context` provider; ours only inside `claude-bridge` |
| 10 | T2 | Session-start preload | native | `session/created`, `systemPrompt.section` |
| 11 | T2 | Turn-end trigger | partial | `turn/end` fire-only; `agent/turn-stopping` + `agent.steer()` = effective refusal; no consumer of ours |
| 12 | T2 | Subagents / background workers | native, unexercised | `ctx.subagents` one-shot/continuable — spike pending (§8.1 dsh-5) |
| 13 | T2 | Output redaction | ours | `secret-guard` |
| 14 | T2 | Plugin logging reaching journald | **missing** | `ctx.logger` dead end; doctrine `process.stderr` |
| 15 | T2 | Skill frontmatter parity (`allowed-tools model argument-hint`) | **missing** | silently dropped; portable contract forbids relying on them |
| 16 | T3 | Agent presets | native + ours | `dsh/presets/*.yaml` → `dsh-presets-render.py`; `pi-preset` |
| 17 | T3 | MCP servers + OAuth | ours | `mcp-registry`, `mcp-proxy`, `ctx.authorization` |
| 18 | T3 | Sandbox | native partial + ours | bwrap/Landlock; `apparmor/bwrap` upgrades to full |
| 19 | T3 | Model capability catalog | ours | `model-catalog` |
| 20 | T4 | Browser surfaces | ours | `chatfile-viewer gh-auth mermaid mobile-mode question-watch ui-kit` |
| 21 | T4 | Module catalog / listing | partial | pnpm only; `reconcilePlugins` re-derives bundles |

### 9.3 Audit order (David 2026-09-06: audit T1 → fix/rewrite → then build)

T1 on both harnesses first — the eight rows that decide whether the marketplace stands: skills discovery + trust (pi 1, dsh 1), filtering (pi 3, dsh 2), package/module install (pi 2/6, dsh 3/4/5), tool gates + policy corpus (pi 4, dsh 6), then the three missing pieces (hooks-as-config, `/name` commands, dsh skills provider). T2 next, gated by the subagent spikes.

---

## 10. T1 audit results (2026-09-06, read-only, three Opus verifiers + one spot-check)

Baselines (all exit 0 in this session): `test_secret_policy_conformance.sh` 6/0 · `test_bash_policy_coverage.sh` 1/0 (+3 declared NOTE gaps) · `test_pi_extensions.sh` 11/0 · `test_policy_tolerance.sh` 8/0 · `test_redact_secret_output.sh` 34/0 · `test_guard_force_push.sh` 52/0 · `test_guard_push_branch.sh` 42/0 · `test_agent_views.sh` 15/0 · `test_agents_wire.sh` 39/0 · `test_pi_e2e.sh` 46/0 · `test_dsh_plugins.sh` 45/0 · dsh guard `node --test` 21/24/19 pass. Node 24 locally (CI = 22, not re-run). `dsh-apply.sh --check` rc 1 = only the branch's uncommitted `gh-auth`/`mermaid` REBUILT rows; `cordis.patch.yml` current; no `.restart-required`.

### 10.1 Defects, ranked

| # | Sev | Area | Finding | Evidence | Fix |
|---|---|---|---|---|---|
| A1 | **CRITICAL** | Claude secrets engine | Python `\b`/`\w` are Unicode-aware, JS's ASCII-only. A token followed by a non-ASCII char is masked **short** and the tail ships (spot-check: Slack token + `é` → 30/44 masked, 14 shipped; `re.ASCII` → 44/44; JS → 44/44). 64/134 mutated corpus cases diverge across ~22 rules. Only Claude affected — the harness in daily use. | auditor fuzz + own repro (`agents/policy/secrets.json` `slack-token`) | OR `re.ASCII` into `agents/harnesses/claude/hooks/_policy.py:_flags()`; corpus passes under it (auditor-verified). Add non-ASCII-adjacency cases to `testcases.json` so all three engines are pinned. |
| A2 | HIGH | pi secret-guard | Fails open **silently** — bare `catch { return; }` at `secret-guard.ts:337-338, :393-394`; forced throw → no stderr, no `ui.notify`. Violates doctrine; `bash-guard.ts:104` and dsh both warn. | empirical | notify + `process.stderr.write` in both catches; add a fail-loud case to `test_pi_extensions.sh`. |
| A3 | HIGH | pi secret-guard | Only `part.type === "text"` is redacted (`secret-guard.ts:349`); nested `tool-result` content arrays and `reasoning` parts pass through. Claude walks all strings; dsh recurses `part.content`. | code + fixture | port dsh's `redactBlocks` recursion; add nested-shape corpus cases. |
| A4 | HIGH | pi filtering | `render-agent-views.py` emits `!<frontmatter name>` but pi matches **directory** names (`package-manager.js:454-476`) — a skill whose dir ≠ name, or nested, is not excluded. Works today only because all 4 skills have dir == name. | probe with fake `$HOME` | emit `!<dir basename>`; assert dir == name in `agents-index.py` and `test_agent_views.sh`. |
| A5 | HIGH | pi filtering | Global `settings.skills` excludes apply only to `~/.pi/agent/skills` + `~/.agents/skills`. They do **not** filter project `.agents/skills` (`:1993`, uses the repo's `.pi/settings.json`) nor **package** skills (need the per-package object form). A marketplace module via `pi install git:` is unfiltered and lands in every request. | probes | design: render per-package filter objects in `settings.packages`; document project scope as unfiltered. |
| A6 | HIGH | dsh filtering | On the `web` profile `dsh-web-app` **disables** the profile `skill-filesystem` row, so the patch-layer `agentsHome` is inert; `$DSH_AGENTS_HOME` from `dsh-run.sh` is the only filter (`--dump-config` lines 162-166; preset rows carry no `agentsHome`). Docs (`cordis.patch.yml:86`, `agents/README.md:154`, CLAUDE.md) call the patch authoritative. A manual/non-interactive `dsh web` launch gets the **unfiltered** tree. | `--dump-config`, `/proc/<pid>/environ` | set `agentsHome` on the preset rows `dsh-presets-render.py` emits; assert `DSH_AGENTS_HOME` in `bootstrap verify`; fix the three docs. |
| A7 | MEDIUM | pi | `pi install` **rewrites `~/.pi/agent/settings.json`**, which `pi-merge.py` render-and-copies — the next `bootstrap sync` drops the package entry. | code | marketplace packages must be declared in `pi/settings.json` (tracked) or captured by `pi-diff.py --pull`; decide in Phase 4. |
| A8 | MEDIUM | pi deny-read | pi refuses only `read`/`grep`; dsh also `edit`/`write`/`read_image`. pi's `edit` returns `details.{diff,patch}` from prior content (`dist/core/tools/edit.js:214-223`), uncovered by the content-only redactor. | code | add `edit`/`write` to pi `READ_TOOLS`. |
| A9 | MEDIUM | policy corpus | 28/52 secret rules have **zero** cases incl. both entropy rules; 0 rules define `allowlist` (dead path); 7/14 `deny_read_paths` uncased. | computed | fill the corpus before the hook runners inherit it. |
| A10 | MEDIUM | bash policy (all 3) | `echo rm -rf / \| bash` allowed — `normalize()` re-anchors heredoc-to-interpreter and `bash -c` but not plain pipe-to-interpreter. Uniform hole. | fuzz | add pipe-to-interpreter re-anchoring + corpus cases. |
| A11 | MEDIUM | dsh skills | `whenToUse` is parsed and shipped over the API but reaches **neither** the model catalog (`dsh-tool-skill` emits name+description) nor the UI. A skill relying on it is invisible. | code | portable contract: selection guidance lives in `description`; drop the `whenToUse`/`when_to_use` pair rule from §3.2. |
| A12 | MEDIUM | dsh skills | **No `$ARGUMENTS` on dsh.** UI `/name` just types into the composer; server injects the SKILL.md body verbatim, user text stays outside. | code | `dsh-module-skills` must implement expansion for `user-invocable` skills (§8.1 dsh-2, now confirmed necessary). |
| A13 | MEDIUM | dsh presets | `pi-mode` preset has **no** skill provider and no `skill` tool. | grep | add rows or document as skill-free. |
| A14 | MEDIUM | both | Project scope (`<repo>/.agents/skills`, rank 200 on dsh; trusted on pi) bypasses the profile tag filter; this repo ships `dsh-browser-verify` with `tags: [homelab]`, and on pi a trusted repo's skill **shadows** a same-named user skill with only a diagnostic. | probes | document the exemption; on pi assert no `collision` diagnostics in `test_pi_e2e.sh`. |
| A15 | LOW | Claude hook | silent on malformed stdin / mid-scan throw (`redact-secret-output.py:127-128, 138-139`). | code | stderr warning. |
| A16 | LOW | tests | conformance gate SKIPs pi arms when `npx esbuild` is unavailable and still exits 0; `test_bash_policy_coverage.sh:26` honors an inherited `DOTFILES_AGENTS_HOME`. | code | fail on SKIP; hard-pin. |
| A17 | LOW | docs | `apply_pi_project_trust` does not exist — trust merge lives in `agents/harnesses/wire.sh:124-148`; CLAUDE.md/spec pointer stale. | grep | fix pointer. |
| A18 | LOW | dsh | flat `<root>/<n>.md` skills get the root as `resourceBase`. | code | marketplace guidance: directory form only. |
| A19 | LOW | dsh verify | nothing on a live host compares the view against `index.yaml`. | — | `render-agent-views.py --check` from `bootstrap verify`. |

### 10.2 Verified-good (keep)

pi: hardcoded `~/.agents/skills`, ancestor walk + trust gate, symlink following, override precedence, dropped skills are absent from the system prompt (not merely hidden), excludes survive the merge order, `agentsdir` before `picfg` by table edge; trust merge is realpath-keyed and never un-trusts. dsh: ranked roots, lowest-rank-wins with a warning, symlinks followed, chokidar re-scans a symlink farm live (no restart), warn-and-drop parsing, running MainPID carries `DSH_AGENTS_HOME`, harness composed after the current patch. Policy: pi and dsh redaction engines agree on 159 inputs; bash gate at parity across all three on 168 inputs; per-rule compile tolerance; wrong-span class covered; DOTFILES_AGENTS_HOME pin covers all conformance arms; all guards wired live.

### 10.3 Marketplace consequences (feed §3/§8)

- pi: a `pi install git:` module is user-scope, unfiltered by our excludes, injected on every request, and its settings entry is clobbered by the next sync (A5, A7). The pi install contract must render per-package filter objects and declare packages in tracked settings.
- dsh: a module's `skills/` are invisible without a provider (confirmed: `roots()` knows nothing of installed packages) — `dsh-module-skills` is mandatory, and it must implement `$ARGUMENTS` (A12) and put selection guidance in `description` (A11).
- Hook runners inherit the policy engines' fail-loud contract; the corpus needs the nine classes the policy auditor listed (non-ASCII adjacency, partial-span, entropy edges, allowlist, nested shapes, deny-read tool coverage, fail-open channel assertions, pipe-to-interpreter, all anchor positions).

### 10.4 How each fix was exercised (and how to exercise it next time)

Every fix below was run by hand in this session against a real input, separately from its unit test. Paths are repo-relative; run from the repo root with `DOTFILES_AGENTS_HOME=$PWD/agents` exported. `uv run --script` is needed for anything importing `yaml`. Never print a real-looking secret in a Bash tool result — the live Claude hook masks it and the probe becomes unreadable; compare lengths or booleans instead.

| # | Recipe | Expected |
|---|---|---|
| A1 | `python3 -c` importing `agents/harnesses/claude/hooks/_policy.py`: `redact(load_secret_policy(), tok+'é')` with an in-bounds synthetic Slack token, check no run of ≥4 token chars survives (prefix, suffix, embedded CJK) | 0 surviving in all positions (pre-fix: 14 chars shipped on suffix) |
| A2 | esbuild `secret-guard.ts` → `.mjs`; register handlers via a stub `pi.on`; call `tool_result` with a part whose `text` getter throws; call `tool_call` with an `input.path` getter that throws | both return `undefined` (fail open); `ctx.ui.notify` called; a `secret-guard: … failed open` line on stderr |
| A3 | same harness; `tool_result` with `{type:'tool-result', content:[{type:'text', text: tok}]}`, `{type:'reasoning', text: tok}`, `{type:'text', text: tok}` | serialized result contains no token; all three parts masked |
| A8 | same harness; `tool_call` for `read`/`grep`/`edit`/`write` with `path` = `~/.aws/credentials` | all four `{block: true}` |
| A9 | Python recount: rule ids in `secrets.json` minus ids cited anywhere in `testcases.json`; rules with `allowlist` | `uncased: []`; `['github-token']` |
| A10 | `_git_push.normalize()` + `_policy.denied_bash()` on `echo rm -rf / \| bash`, `printf "rm -rf /" \| sh`, `echo "rm -rf /" \| grep rm`; `node -e import(...bash-guard/lib/normalize.js).normalize(...)` on the same | first two denied, grep case allowed; JS `normalize()` text identical to Python |
| A15 | `echo 'not json' \| python3 agents/harnesses/claude/hooks/redact-secret-output.py; echo rc=$?` | one stderr warning, `rc=0` |
| A16 | `DOTFILES_AGENTS_HOME=/nonexistent bash tests/test_bash_policy_coverage.sh` · a stub `npx` that exits 1 first on `PATH` then `bash tests/test_secret_policy_conformance.sh` | first still 1/0 (inherited value ignored); second `FAIL: pi engine`, `FAIL: pi bash engine`, rc 1 — not SKIP |
| A4 | fixture tree with `skills/actual-dir/SKILL.md` (`name: renamed`, `harness: [claude]`) + nested `skills/nested/deep/`; `bin/agents-index.py --write`; `render-agent-views.py --tree … --env host --pi-excludes-file out.json` | `out.json` = `{"skills": ["!skills/actual-dir"]}` — directory path, not `renamed` |
| A19 | same tree: `render-agent-views.py … --check` clean, then add a skill + re-index, `--check` again | rc 0 "current" → rc 1 "views are stale", naming the pending pattern |
| A5 | `pi-merge.py --target settings --base pi/settings.json --local {} --local-host <overlay with skills:["!x"] and packages:[str, {source,skills:["+y"]}, {source,skills:[]}]> --local-container {} --env host` (stdout is the merge) | string → `{source, skills:["!x"]}`; object → user's `+y` kept, `!x` appended; `skills: []` untouched |
| A7 | render the merge into `$D/settings.json`, append a package `pi install` would add, `PI_CODING_AGENT_DIR=$D python3 scripts/pi-diff.py --target settings` (and `--json 2>err`) | "⚠ 1 package(s) in the live file are NOT declared…" with the line to paste; with `--json` stdout parses, warning on stderr |
| A17 | fake `HOME` with `trust.json` `{"<repoA>": false}`, list file naming repoA + repoB, `wire.sh --pi --env host --agents-home … --trust-list list` | `pi trust: SKIPPED <repoA> — explicitly distrusted`, repoB added, repoA stays `false` |
| A14 | `comm -12 <(ls agents/skills) <(ls .agents/skills)` | empty |
| A6 | `DSH_HOME=<scratch> XDG_CACHE_HOME=<fake cache with dotfiles/agents-views/dsh/skills> uv run --script scripts/dsh-presets-render.py`; read the rendered `standard-mcp/agent.cordis.yml` `skill-filesystem` row · read-only on the live host: `uv run --script scripts/dsh-presets-render.py --check` | row carries `config.agentsHome: '<fake view>'` · live: both forks STALE until `bootstrap sync`, `pi-mode: current` |
| A11 A12 A18 | fixture root with a `whenToUse`-only skill, a `$ARGUMENTS` body with `harness: [..dsh]`, and a flat `flat.md`; `uv run --script agents/bin/lint-skills.py <root>` | WARN (whenToUse not in description), WARN ($ARGUMENTS on dsh), FAIL (flat file); rc 1 |
| A13 | `grep -n SKILL-FREE dsh/presets/pi-mode.yaml` | the rationale block |

Side findings while exercising (follow-ups, not fixed here): the `named_assignment` secret rule masks our own hook's warning prefix (`redact-secret-output: …`) and grep lines like `secret-guard.ts:200:export function …` when they flow through a Bash tool result — a false-positive class the corpus should carry `allow` cases for; `test_pi_e2e.sh` and `test_dsh_posture_selection.sh` fail on `origin/main` for environmental reasons (live `~/.pi/agent/settings.json` drift; dsh CLI arg mismatch) and are untouched.

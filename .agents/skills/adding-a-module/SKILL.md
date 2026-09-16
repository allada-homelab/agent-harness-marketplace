---
name: adding-a-module
description: How to add a new module, or a new skill to an existing module, in the agent-harness-marketplace repo — the exact files, the manifests that must agree, the generated files to regenerate, and the checks that must pass. Use when creating or modifying anything under modules/, when bin/check.sh fails, or when asked to "add a skill/plugin/module" to this repo.
---

# Adding to agent-harness-marketplace

One content tree, three harnesses. Every module under `modules/<name>/` installs
natively on Claude Code, pi and dsh from the same directory: the shared content
is Agent Skills (`skills/<skill>/SKILL.md`), and each harness reads its own thin
manifest beside them.

**Read `docs/authoring.md` first.** It is the portable `SKILL.md` contract — which
frontmatter keys survive all three parsers, why assets are skill-relative, when to
scope with `harness: [claude]`. This skill does not repeat it; it covers the
procedure around it and the failures that contract doesn't catch. Every path below
is relative to the repo root.

## Decide what you are adding

| You are adding | Do this |
|---|---|
| A skill to an existing module | Create `skills/<skill>/SKILL.md`, bump that module's version everywhere it appears (`package.json`, and `plugin.json` + the marketplace entry if it has them), regenerate the index, verify. |
| Agents | Create `agents/<name>.md` in Claude's shape (`name` == filename, `description`, optional `tools`, `model`). Read `agent-contract/README.md` first — see "Agent tools" below for how the `tools:` list is treated on pi and dsh. |
| A new module | Full procedure below. |
| Hooks | `hooks/hooks.json` in Claude's shape, `"type": "command"` handlers, event keys drawn from `hook-contract/events.json`, and every `CLAUDE_PLUGIN_ROOT`-prefixed command path resolving to a file that ships in the module. Read `hook-contract/README.md` for the stdin/stdout contract and the two fidelity gaps. |
| Workflows | `workflows/*.js` in Claude's shape: a pure-literal `export const meta = {name, description, phases?}` and a body built from `agent()`/`parallel()`/`pipeline()`. The filename is the `<module>:<name>` dispatch id off Claude. Read `workflow-contract/README.md`; `bin/lint-workflows.py` enforces the literal. |
| MCP servers | One `mcp.json` at the module root (Agent Plugins v1 shape). `.mcp.json` beside it is generated — see step 5 — and `docs/authoring.md` has the two shapes and the rules the gate enforces. |
| A pi extension (`extensions/`) or dsh plugin code (`lib/`) | **Stop and ask.** The conformance tests currently forbid both outright — `tests/conformance/pi.test.mjs` and `dsh.test.mjs` assert no module contains either. The harness-side foundation left this repo; reintroducing executable code is a repo-shape decision, not a module change. |

## Agent tools

An agent file's `tools:` (and a forked skill's `allowed-tools:`) is written in
**Claude's tool names** and translated per harness by the pi and dsh bridges. A
name a harness does not have is **dropped with one warning line** — by design,
never an error. The contract table is `agent-contract/README.md`; the pi bridge
warns `pi has no <name>; dropped from its tool allowlist` and the dsh bridge
warns `no dsh equivalent for <name>`.

Our standing decision is to **keep the full tool list and embrace the
drop-with-a-warning** rather than trim to the intersection that exists on every
harness. The dropped names are informational (pi runs and exits 0; dsh omits
`toolFilter`), and the read-only capability the agent actually uses is
unaffected. It also lets one file declare harness-specific tool spellings — e.g.
`read-image` and `ReadImage` both listed — so each harness uses the name it
knows and drops the other. Do not trim a `tools:` list purely to silence the
startup warning; see `CLAUDE.md` → "Constraints that bite".

## New module, step by step

### 1. Name it

The directory name is the identity and three files must agree with it:
`modules/<name>/`, `plugin.json` `"name": "<name>"`, `package.json`
`"name": "@allada-homelab/<name>"`. A skill directory's name must equal its
`SKILL.md` frontmatter `name`.

### 2. Create the files

```
modules/<name>/
  package.json                     # every module needs one; it carries the version
  .claude-plugin/plugin.json       # only if Claude should install it as a plugin
  plugin.json                      # GENERATED (Agent Plugins v1) — never hand-edit; step 5 renders it
  cordis.patch.yml                 # required whenever the module has skills/ or a dsh key
  mcp.json                         # optional: MCP servers (Agent Plugins v1 shape)
  .mcp.json                        # GENERATED from mcp.json — the spelling Claude reads; step 5
  README.md                        # convention: every module has one
  skills/<skill>/SKILL.md
  skills/<skill>/references/*.md   # optional assets, referenced skill-relative
```

`package.json` — copy this, changing name/description:

```json
{
  "name": "@allada-homelab/<name>",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "description": "<one line; this becomes the module description in modules/index.yaml>",
  "license": "MIT",
  "pi": { "skills": ["skills/*"] },
  "dsh": { "bundle": { "patch": "./cordis.patch.yml" } }
}
```

`.claude-plugin/plugin.json` — the version must match `package.json` exactly:

```json
{
  "name": "<name>",
  "version": "0.1.0",
  "description": "<same one line>",
  "author": { "name": "David Allada", "email": "davidanilallada@gmail.com" },
  "license": "MIT"
}
```

`cordis.patch.yml` — for a **content module** (has `skills/`, no `lib/`) this file
must be **empty**. The file must exist and `package.json` must carry the
`dsh.bundle.patch` key; dsh installs a package without that key as a plain
dependency and silently ignores the patch.

```yaml
# Empty on purpose. This module is a dsh BUNDLE (package.json `dsh.bundle`)
# so the harness lists it in the profile's dsh.profile.bundles — and the
# always-installed skills bridge in the maintainer's harness layer discovers
# every bundle that ships skills/. Nothing to insert.
[]
```

### 3. Add the marketplace entry

A module with `.claude-plugin/plugin.json` **must** have an entry in the repo's
`.claude-plugin/marketplace.json`, with the same version and
`"source": "./modules/<name>"`. A module without `plugin.json` must **not** have
one. Both directions fail the check.

```json
{
  "name": "<name>",
  "description": "<same one line>",
  "category": "development",
  "version": "0.1.0",
  "source": "./modules/<name>"
}
```

### 4. Reconcile the root pi manifest

pi installs the whole repo, so the **root** `package.json` `pi.skills` decides
what every pi user gets:

- If **any** skill in the module applies to pi (no `harness:` key means all three),
  leave the root manifest alone — `modules/*/skills/*` already globs it in.
- If **every** skill is scoped away from pi (`harness: [claude]`, say), add
  `"!modules/<name>/**"` to the root `pi.skills` array.

Getting this backwards fails in both directions.

### 5. Regenerate the generated files

`modules/index.yaml`, every `modules/<name>/plugin.json` and every
`modules/<name>/.mcp.json` are generated — never hand-edit them.

```
uv run --script bin/render-index.py --write
uv run --script bin/render-plugin-manifests.py --write
```

`plugin.json` is the [Agent Plugins v1](https://agent-plugins.org/specification)
manifest, rendered from the module's `package.json` (name from the directory,
version, description, license) so the module installs in Cursor, Codex, Copilot,
Kiro and VS Code as well. It carries the version too, so a bump must be followed
by a re-render or the `plugin.json is current` step fails.

Module `description` comes from the module's `package.json`; each skill's
`summary` is the **first sentence** of its `SKILL.md` `description`, so write that
first sentence to stand alone.

### 6. Verify

```
bin/check.sh                              # the deterministic gate
CHECK_BASE=origin/main bin/check.sh       # + the changed-module version-bump rule
bin/check.sh --no-node                    # same minus the pnpm/node suites
```

`bin/check.sh` is **not** all of CI. Three things differ locally:

- The **smoke job is separate** and `check.sh` never invokes it. To reproduce:
  `npm install -g @earendil-works/pi-coding-agent @deepseek-ai/dsh`, then
  `bash tests/smoke/pi.sh` and `bash tests/smoke/dsh.sh`.
- The **version-bump-on-change** step is inert unless you set `CHECK_BASE`; CI
  always sets `origin/main`.
- **`claude plugin validate`** is silently skipped when the `claude` CLI is not on
  PATH locally, but hard-fails in CI.

Capture the baseline before you start: a failure in a module you did not touch is
not yours to fix in this change, but you must say so rather than report a green
gate.

### 7. Ship

Branch off `main`, one atomic commit, open a PR. CI runs `check` (that is
`CHECK_BASE=origin/main ./bin/check.sh`, full, no `--no-node`) and `smoke` (pi and
dsh installed from npm for real). Both must be green.

On merge, a third job cuts the **repo** tag automatically: a merge that changed
anything under `modules/` gets the next patch tag, one that didn't gets none. Do
not tag by hand for a normal release — only to move the minor or major, which the
job never does on its own. This is separate from the module version you bumped in
step 2; both exist, and neither derives from the other.

### 8. Pair with the fleet

Merging here ships nothing to a machine. The fleet consumes this repo through
the dotfiles repo's `agents/modules.tsv` (one row per module: repo, pinned tag,
module, claude/pi/dsh on|off, why), and `CLAUDE.md` → "Pairing with the fleet"
lists the six cases that need a dotfiles change. For a module change the usual
pairing is: a new row (new module) or the row deleted (removed module), the `ref`
bumped to the tag the merge cut, and — for a port of an official plugin —
`<name>@claude-plugins-official` set to `false` in the fleet's
`claude/settings.json`. `bin/fleet-pairing.sh` prints the drift when the
dotfiles checkout is on this machine. **State the paired change in the
handoff**, or state that none is needed; do not leave it to be rediscovered.

## Porting a Claude Code plugin

Most modules here are ports of a plugin from `anthropics/claude-plugins-official`
(or another Claude-only marketplace). `modules/code-review` (PR #34) and
`modules/code-simplifier` (PR #39) are the reference ports; open one beside the
upstream plugin before starting. The port is the same module procedure above
plus a fixed set of translations — and the upstream shape is never copied as-is.

### Fetch the upstream

```
D=$(mktemp -d) && git clone -q --depth 1 --filter=blob:none --sparse \
  https://github.com/anthropics/claude-plugins-official "$D" \
  && git -C "$D" sparse-checkout set plugins/<name>
```

Read every file: `.claude-plugin/plugin.json`, `commands/`, `agents/`,
`skills/`, `hooks/`, `LICENSE`. The plugin's own README often describes
behavior the files do not implement; the files are the source of truth.

### Translation table

| Upstream has | Do this | Why |
|---|---|---|
| `commands/<x>.md` | `skills/<x>/SKILL.md` with `user-invocable: true` + `argument-hint`; body verbatim, then adapted | commands are skills here; dsh and pi have no `commands/` |
| `agents/<x>.md` with `model: opus\|sonnet\|haiku` | drop the `model` key | the module is **model-agnostic**: every child inherits the session model on all three harnesses (standing decision, PR #34) |
| "use a Haiku/Sonnet agent for step N" in a command body | one `agents/<role>.md` per role, no `model` key; the skill names the type `<module>:<role>` | tiers pinned in prose are invisible to pi/dsh; agent files are dispatchable everywhere |
| `allowed-tools:` on a command or agent-less skill | delete it; write the discipline as prose ("read-only: use `gh` to read, never edit") | dsh drops the key silently — a restriction that vanishes is worse than none |
| `tools:` on an agent | keep, in Claude spellings; add a `tools:` list if upstream has none and the agent's capability is obvious | the bridges translate; see "Agent tools" above |
| hardcoded house style ("ES modules, `function` over arrows, React Props types") | replace with "read the project's `CLAUDE.md` / `AGENTS.md` and match the surrounding code" | that list is Anthropic's own repo convention, not the user's |
| "CLAUDE.md" as the only guideline file | `CLAUDE.md` **and** `AGENTS.md` | dsh and pi projects use `AGENTS.md` |
| "operates proactively after every edit" / auto-trigger prose | drop it; ship a user-invocable skill as the entrypoint and say so in the README | proactive agent triggering is Claude-only; pi and dsh need an invocation |
| an agent-only plugin (no command) | still ship one thin skill that dispatches the agent | pi's `delegate_agent` is inactive until a module skill is invoked; a module with only `agents/` has no way in |
| `$ARGUMENTS` in a command | keep, but write the sentence to read with the token unexpanded ("Scope: $ARGUMENTS — when none is given, …") and define the default | dsh expands only through the bridge |
| "Claude Code" / "Claude" in user-facing output (comment footers, reports) | neutral wording | the same text ships from three harnesses |
| `hooks/hooks.json` | keep Claude's shape; check `hook-contract/README.md` for the two fidelity gaps | runs through the hook runners |
| `${CLAUDE_PLUGIN_ROOT}`, absolute paths, bang-backtick shell injection | only allowed under `harness: [claude]` — otherwise rewrite skill-relative | portability lint |
| `mcp.json` / `.mcp.json` | keep `mcp.json` only; `.mcp.json` is regenerated | see "MCP servers" in `docs/authoring.md` |
| upstream `LICENSE` (Apache-2.0 for the official plugins) | keep the module at MIT like its siblings, but the README's **Provenance** section names the upstream, its license, and each change | attribution notice; also the audit trail for the next porter |

### What every port's README carries

Copy the shape of `modules/code-review/README.md`: what a run does as a
numbered list, per-harness install lines, and a **Provenance** section that
lists every deviation from upstream and closes with what is *unchanged* (the
rubric, thresholds, principles). The unchanged list is what a future re-sync
against upstream diffs against.

### Skill wrapper phrasing

When the skill dispatches agents, use the per-harness block from
`modules/code-review/skills/code-review/SKILL.md` verbatim (Agent tool on
Claude Code, `delegate_agent` on pi/dsh with the `/agents` hint, sequential
inline fallback pointing at `./../../agents/`), and remind the model that a
child sees none of the conversation so every input must be passed explicitly.

### Port-specific traps

- **Name collisions with built-ins.** Claude Code ships `/simplify`,
  `/code-review`, `/security-review`, `/init`; a skill with the same name is
  ambiguous. Name the skill after the module (`code-simplifier`), not the verb.
- **`pnpm-lock.yaml` changes on the first `bin/check.sh`** because the new
  module is a workspace project. Commit it — CI installs with a frozen lockfile.
- **The version is 0.1.0, not upstream's.** Module versions are ours; the
  upstream version goes in the Provenance section if it matters.
- **Do not port the README's promises.** If upstream's README claims a step
  the files never perform, the port performs what the files do.

## Traps

These pass a casual reading and fail the gate:

- **Do not copy `cordis.patch.yml` from an older module without reading it.**
  Content modules used to carry loader `insert:` rows; since the harness-side
  foundation left this repo the file must be empty. A stale copy fails
  `content modules: empty dsh patch`.
- **`plugin.json` and the marketplace entry travel together**, at the same
  version as `package.json`. Three places, one version.
- **The asset-exists lint only fires on paths written with a `./` prefix.**
  `references/x.md` in a SKILL.md body is *not* checked and will ship broken;
  write `./references/x.md`.
- **Never hand-edit `modules/index.yaml` or `modules/<name>/plugin.json`** —
  regenerate them, or the `is current` steps fail.
- **No absolute or `~/` paths** anywhere under `modules/`, `docs/` or `README.md`,
  and no homelab hostnames or RFC1918 addresses. There is a grep for it.
- **A changed module must bump its version.** CI checks this against
  `origin/main`; locally the step is skipped unless `CHECK_BASE` is set. pi and
  dsh install at a tag, so an unbumped change is invisible to them.
- **`harness:` unlocks the Claude-only keys only when the scope is *exactly*
  `[claude]`.** `harness: [claude, pi]` still gets every portability check, so
  `allowed-tools`, `model`, `CLAUDE_*` placeholders, absolute paths and
  bang-backtick shell injection all still fail there.
- **Never write a bang immediately followed by a backtick in any SKILL.md body,
  even inside a code span.** Claude Code's skill loader executes it as a shell
  command at load time and the skill fails to load — a stricter rule than the
  repo lint, which only catches it at the start of a line.
- **A `description` over 1024 characters fails the lint** — pi sends it on every
  request of the agentic loop.
- **Leftover `node_modules/` in a deleted module's directory** makes `check.sh`
  treat it as a module missing its `package.json`. Remove the stale directory.

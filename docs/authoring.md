# Authoring a module

## Layout

```
modules/<name>/
  .claude-plugin/plugin.json   # Claude: {name, version, description, author, license} — name == directory
  package.json                 # every module: {"name": "@allada-homelab/<name>", "version", "pi": {…}}
                               #   + "dsh": {"bundle": {"patch": "./cordis.patch.yml"}} on dsh code modules
  cordis.patch.yml             # dsh loader rows; a content module inserts one dsh-module-skills row
  skills/<skill>/SKILL.md      # THE shared content — commands are skills
  extensions/<n>.ts            # pi adapter (optional; event-only, no registerTool)
  hooks/hooks.json             # Claude-shaped hooks; runs on pi/dsh through the hook runners
  lib/index.js                 # dsh adapter (optional)
  test/  README.md
```

A module with a `.claude-plugin/plugin.json` must have an entry in
`.claude-plugin/marketplace.json` with the same version. Bump all three when the
module changes; `bin/check.sh` asserts they agree.

## The portable `SKILL.md` contract

Enforced by `bin/lint-skills.py` (run through `bin/check.sh`).

- **Required**: `name` (== the directory name; Claude requires it, pi and dsh
  tolerate) and `description`. One tight paragraph: pi sends every loaded
  skill's name and description on every API request of the agentic loop, so a
  description must earn its line.
- **Allowed**: `argument-hint`, `user-invocable`, `disable-model-invocation`,
  `license`, `compatibility`, `metadata`, `harness: [claude|pi|dsh]`, `tags: […]`.
  `harness` and `tags` are this marketplace's selection vocabulary; every harness
  ignores them, so they are safe to publish.
- **Selection guidance lives in `description`.** dsh parses `whenToUse` and ships
  it over the API, but its skill catalog emits name and description only and the
  UI never renders it. Nothing may live there that the description lacks.
- **Directory form only**: `skills/<name>/SKILL.md`, never `skills/<name>.md`.
  dsh accepts the flat form and then hands the skill the *root* as its resource
  base, so `./scripts/x.py` resolves into the directory shared with every sibling.
- **A command** is `user-invocable: true` plus `argument-hint` (add
  `disable-model-invocation: true` when the model must never trigger it). It is
  `/name` on Claude, `/skill:name` on pi (`/name` with skill-commands-pi) and
  `/name` on dsh through dsh-module-skills.
- **Substitutions**: `$ARGUMENTS` and `$N` only. Claude and pi expand them
  natively; dsh expands them only through dsh-module-skills, so write the body so
  it still reads correctly with the token unexpanded and the user's text
  following as prose ("Research target: $ARGUMENTS").
- **Forbidden** in a portable skill: `context: fork`, `agent:`, `hooks:`,
  `effort:`, `model:`, `allowed-tools:` (dsh drops it silently, and a tool
  restriction that vanishes is worse than none), `${CLAUDE_*}` placeholders,
  absolute or `~/` paths, and `` !`cmd` `` injection. A skill that needs one of
  these is Claude-only: scope it with `harness: [claude]` and the lint allows the
  Claude keys. Put harness-specific behavior in a sibling skill or module rather
  than in the shared one.
- **Assets** are referenced skill-relative (`./scripts/x.py`,
  `./references/y.md`) and must exist; the lint checks.

## Hooks

Ship one `hooks/hooks.json` in Claude's shape with `"type": "command"` handlers
and `${CLAUDE_PLUGIN_ROOT}` paths. Claude reads it natively; hook-runner-pi and
hook-runner-dsh map it onto their harness's seams. Read
[`hook-contract/README.md`](../hook-contract/README.md) for the exact stdin and
stdout contract and the two known fidelity gaps: `Stop` cannot block on pi (a
block becomes a follow-up user message) and `PreToolUse` cannot rewrite on dsh
(a rewrite becomes a deny whose reason carries the intended input). Turn-end
work should therefore run *after* the turn in the background on every harness.

## Checking

```
bin/check.sh              # everything; what CI runs
bin/lint-skills.py        # just the skill contract
bin/render-index.py --write
```

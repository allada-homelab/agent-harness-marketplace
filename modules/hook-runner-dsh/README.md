# hook-runner-dsh

Runs a marketplace module's Claude-shaped `hooks/hooks.json` natively on the
**DeepSeek Harness**.

## What and why

A module in this marketplace ships **one** hooks manifest, in Claude Code's
shape ([`hook-contract/README.md`](../../hook-contract/README.md)). Claude reads
that file itself. dsh has no such file — it has *seams*: a tool pipeline, a
system-prompt registry, an agent loop. This plugin is the adapter: it finds every
installed module's manifest and maps each Claude event onto the dsh seam that
does the same job, so a module author writes the hook once and it works on all
three harnesses.

It is deliberately generic. It knows nothing about any particular module, holds
no policy of its own, and registers no tools or services — a profile with no
hook-carrying module installed pays nothing per turn.

## Mapping

| Claude event | dsh seam | Fidelity |
|---|---|---|
| `SessionStart` | `session/created` → a `systemPrompt.context` entry | full, with a caveat |
| `UserPromptSubmit` | `agent/pre-step` → a `systemPrompt.context` entry | full |
| `PreToolUse` | `tools/pre-execute` → `{kind:'allow'}` / `{kind:'deny', reason}` | **degraded: no rewrite** |
| `PostToolUse` | `tools/post-execute` → `additionalContexts` | full |
| `Stop` | `agent/turn-stopping` → `agent.steer(reason)` | full |

**PreToolUse cannot rewrite.** `PreToolDecision` has no rewrite variant
(`@deepseek-ai/dsh-tools` `lib/types/index.d.ts:418`) and `exec.arguments` is
deep-frozen before the waterfall runs (`lib/index.js:3047`, waterfall at
`:3105`). A hook's `updatedInput` therefore becomes a **deny whose reason states
the input the hook wanted**, e.g.

```
PreToolUse hook rewrote this call; dsh cannot apply a rewrite, so re-issue it
as: {"command":"echo rewritten; ls"}
```

so the model can re-issue the corrected call. The runner still attempts an
in-place rewrite first, guarded by `Object.isFrozen`, so a future dsh that opens
that channel becomes full-fidelity with no change here. Running the original
command instead would silently discard the hook's intent — which for a hook that
exists to *narrow* a command is the dangerous direction.

**Context injection is text on the model-facing surface.** dsh has no
"additionalContext" field. `SessionStart` and `UserPromptSubmit` text is
published as a `systemPrompt.context` entry (a durable user-role snapshot,
`@deepseek-ai/dsh-system-prompt` `lib/types/index.d.ts:71`); `PostToolUse` text
rides the seam's own `additionalContexts` channel
(`@deepseek-ai/dsh-tools` `lib/types/index.d.ts:435`).

**`UserPromptSubmit` runs at `agent/pre-step`, not at assembly.** The
`AssembleContext` a prompt provider receives carries no prompt
(`lib/types/index.d.ts:37`), and a provider is synchronous while a hook is a
subprocess. `agent/pre-step` is the awaited waterfall carrying the messages
claimed for the step (`@deepseek-ai/dsh-agent`
`lib/types/runtime-types.d.ts:235`), so the handlers finish *before* the
assembly that must show their text, and the provider is a pure read.

**`SessionStart`'s caveat:** `session/created` is a synchronous emit, so the run
cannot be awaited there. The first `agent/pre-step` awaits it before the first
assembly, which is what keeps the text from missing its own session.

**`Stop` is a real refusal.** A `{"decision":"block","reason":"…"}` steers the
agent (`agent.steer`), and the machine re-reads its inbox and runs another step
instead of closing the turn (`lib/types/runtime-types.d.ts:285-301`). The second
fire carries `stop_hook_active: true`, which is what lets a hook stop its own
loop.

**Tool names and inputs** are translated both ways per the contract: dsh
`bash→Bash read→Read write→Write edit→Edit grep→Grep glob→Glob`, and dsh's
`path` argument becomes Claude's `file_path`. An unknown tool keeps its native
name and its native argument shape.

**Failure posture.** A handler that crashes, times out, or names a script that
does not exist is a *failed* handler: the action **proceeds** and exactly one
line containing `hook-runner` goes to `process.stderr`. (`ctx.logger` is not used
for those lines — it does not reach the journal a user reads afterwards.) A
missing script is detected before the spawn, because `python3 /gone.py` exits
`2`, which is also the contract's *block* code.

## Install

```sh
dsh plugin --profile <p> add "github:allada-homelab/agent-harness-marketplace#vX&path:/modules/hook-runner-dsh"
```

That is the whole install for the runner. Installing a **module** the same way is
then enough for its hooks to run — see discovery below.

## Configuration

```yaml
- id: hook-runner-dsh
  name: '@allada-homelab/hook-runner-dsh'
  config:
    manifests: []
```

`manifests` — absolute paths to a `hooks.json`, or to a module directory (its
`hooks/hooks.json` is implied). Empty by default.

## How a module's hooks.json gets picked up

Two sources, unioned and deduped by realpath:

1. **Auto-discovery** (the default path). The runner reads its own profile's
   `package.json`, walks `dsh.profile.bundles`, `createRequire`-resolves each
   bundle, and keeps every one that ships `hooks/hooks.json`. So
   `dsh plugin --profile <p> add <module>` is all a module needs — no second
   config edit. The profile directory is found by walking up from this plugin's
   own file to the nearest `package.json` declaring `dsh.profile.bundles`, which
   is by construction the profile (`$DSH_HOME/profiles/<name>`,
   `@deepseek-ai/dsh-app-boot` `lib/index.js:318`).
2. **`config.manifests`** (the fleet path). Explicit paths, for a
   config-managed profile that wants the set pinned rather than inferred.

Installed modules are trusted by installation: there is no trust gate and no
repo scanning. A manifest that will not parse, or a path that does not exist, is
skipped with one loud line — never a boot failure, because a broken module must
not cost a user their harness.

## Tests

```sh
node --test test/*.test.mjs
```

`test/corpus.test.mjs` runs **every** case in
[`hook-contract/corpus.json`](../../hook-contract/corpus.json) whose `harness`
list includes `dsh` through the real seams, with the fixture scripts actually
executed and `exec.arguments` frozen exactly as dsh freezes them.
`test/discovery.test.mjs` covers discovery against a fake profile tree.

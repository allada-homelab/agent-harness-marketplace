# hook-runner-pi

Runs Claude Code `hooks/hooks.json` manifests on **pi**.

A module in this marketplace ships one `hooks/hooks.json` in Claude Code's
shape. Claude reads it natively. This extension reads the same file and maps
each event onto pi's native extension seam, so a module's hooks are a product
surface rather than a Claude-only feature. The contract it is held to —
manifest shape, process contract, and the conformance corpus — is
[`hook-contract/README.md`](../../hook-contract/README.md).

It is **event-only**: no `registerTool`, no prompt text, 0 tokens per turn.

## Event mapping

| Claude event | pi seam | What the runner does | Fidelity |
|---|---|---|---|
| `SessionStart` | `session_start` | `hookSpecificOutput.additionalContext` becomes a custom message via `pi.sendMessage(..., { deliverAs: "nextTurn" })`, so it is in context for the first prompt without triggering a turn | full |
| `UserPromptSubmit` | `before_agent_start` | stdin carries `prompt`; `additionalContext` is returned as `{ message }` for this turn | full |
| `PreToolUse` | `tool_call` | exit 2 or `permissionDecision: "deny"` → `{ block: true, reason }`; `updatedInput` is translated back to pi's native argument names and applied in place | full |
| `PostToolUse` | `tool_result` | stdin carries `tool_response` (the text parts concatenated); `additionalContext` is appended as an extra text part | full |
| `Stop` | `agent_settled` | observe only; a top-level `{"decision":"block","reason"}` becomes one `pi.sendUserMessage(reason)` | **degraded** |

### Why `Stop` is degraded

`agent_settled` is fire-only: pi has already stopped and nothing an extension
returns can refuse that. A `Stop` hook's `block` therefore does not suppress
the stop the user already saw — it adds one more user message, restarting the
agent. The follow-up fires **once**: after it is sent, subsequent `Stop` runs
carry `stop_hook_active: true` so a hook can see it and stay quiet. Unlike
Claude, this flag is latched for the rest of the session rather than reset per
user prompt, because the runner's own follow-up is indistinguishable from a
real prompt on this seam. Loop safety wins.

### Tool translation

Native pi names become Claude names before `matcher` is applied
(`bash→Bash read→Read write→Write edit→Edit grep→Grep find/glob→Glob`); an
unknown tool (an MCP tool, say) keeps its own name and its arguments pass
through untouched. Arguments are translated too, because pi's schemas differ
from Claude's: pi's `read`/`write`/`edit` take `path`, not `file_path`.

One lossy edge: Claude's `Edit` is a single `old_string`/`new_string` pair
while pi's `edit` carries an `edits[]` array. The hook sees `edits[0]`, and a
rewrite is applied to `edits[0]`.

## Manifest discovery

Two sources, deduped by realpath, in this order:

1. **Sibling modules.** This file resolves its own location
   (`<root>/modules/hook-runner-pi/extensions/hook-runner.ts`) and loads
   `<root>/modules/*/hooks/hooks.json`. That works from any install root pi
   picked — `~/.pi/agent/git/...`, a local path install, a worktree — without
   reading pi's settings for the location. A sibling module that pi's own
   package filter switches off is skipped: the runner reads every git package
   entry in pi's `settings.json` (`$PI_CODING_AGENT_DIR`, default
   `~/.pi/agent`) and treats each `!modules/<name>/**` pattern on `skills` or
   `extensions` as "no hooks either" — otherwise a module an operator turned
   off for pi would keep running its lifecycle and tool hooks on every start.
   `$PI_HOOK_EXCLUDE_MODULES` (comma-separated names) adds to that list.
2. **`$PI_HOOK_MANIFESTS`**, colon-separated. Each entry is either a
   `hooks.json` path or a module directory containing `hooks/hooks.json`. This
   is the dotfiles/fleet path, where the modules are not siblings.

**Not loaded: `<cwd>/.claude/hooks.json`.** Project-local hooks are controlled
by anyone who can open a PR against a repo you clone, they execute arbitrary
commands, and pi offers no trust prompt at this seam. Claude gates them behind
its own; we decline instead.

`${CLAUDE_PLUGIN_ROOT}` expands to the module directory that owns the manifest
(the parent of `hooks/`); `${CLAUDE_PROJECT_DIR}` expands to `process.cwd()`.
Both are also exported to the handler's environment.

## Fail open and loud

A handler that crashes, times out (`timeout` seconds, default 60), or whose
script does not exist lets the action **proceed** and writes one line
containing `hook-runner` to `process.stderr` (and `ctx.ui.notify` when a
context is available). A missing script is checked before the spawn on
purpose: `python3 missing.py` exits 2, and exit 2 is the contract's *block*
channel — honoring it would turn a deleted hook into a hard denial.

Non-`command` handlers (`http`, `mcp_tool`, `prompt`, `agent`) are Claude-only
and are skipped with one stderr line.

## Install

```bash
pi install git:github.com/allada-homelab/agent-harness-marketplace@v1
```

The extension is loaded by the repo-root pi package manifest
(`pi.extensions: ["modules/*/extensions/*.ts"]`). For a fleet/dotfiles install
that does not use the marketplace layout, point `$PI_HOOK_MANIFESTS` at the
manifests:

```bash
export PI_HOOK_MANIFESTS="$HOME/.agents/modules/okf-wiki:/path/to/other/hooks/hooks.json"
```

## Test

```bash
cd modules/hook-runner-pi && npm test
```

`node --test` bundles the extension with the pinned `esbuild` devDependency
(`pnpm install` at the repo root; no network fetch at test time), wires the
default export to a fake pi API, and runs **every** `hook-contract/corpus.json`
case whose `harness` includes `pi`, executing the real fixture scripts. If
esbuild is missing the suite fails rather than skips.

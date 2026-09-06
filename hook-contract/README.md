# The hook contract

A module ships **one** `hooks/hooks.json` in Claude Code's shape, and it runs on
all three harnesses. Claude reads the file natively. On pi and dsh a generic
runner (`modules/hook-runner-pi`, `modules/hook-runner-dsh`) reads the same file
and maps each event onto the harness's native seam. This directory is the
contract both runners are held to: `corpus.json` is the conformance corpus, and
`fixtures/` are the hook scripts the corpus invokes.

## Manifest

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash|Write", "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/gate.py\"", "timeout": 10 } ] }
    ]
  }
}
```

- Only `"type": "command"` handlers are portable. `http`, `mcp_tool`, `prompt`
  and `agent` handlers are Claude-only; runners skip them with one stderr line.
- `matcher` is a regex over the **Claude** tool name (`Bash`, `Read`, `Write`,
  `Edit`, `Grep`, `Glob`, `Agent`, `Skill`, `WebFetch`, …). Runners translate the
  harness's native tool name to the Claude name before matching (table below);
  an unknown native tool is matched under its own name. Omitted or `""` matches
  everything.
- `${CLAUDE_PLUGIN_ROOT}` expands to the module directory. `${CLAUDE_PROJECT_DIR}`
  expands to the project root. No other placeholder is portable.
- `timeout` is seconds, default 60. A timed-out handler is a **failed** handler.

## Process contract

- The event JSON is written to the handler's **stdin**.
- Exit `0`: proceed. Stdout is parsed as JSON if it parses; a
  `hookSpecificOutput` object is honored (below); any other text is ignored.
- Exit `2`: **block**. Stderr is the reason shown to the model.
- Any other exit, a crash, or a timeout: the handler **failed**. Runners fail
  **open and loud** — the action proceeds, one line goes to `process.stderr`.

Common stdin fields: `session_id`, `cwd`, `hook_event_name`. Per event:

| Event | Extra stdin fields | Honored stdout |
|---|---|---|
| `SessionStart` | `source: "startup"` | `hookSpecificOutput.additionalContext` |
| `UserPromptSubmit` | `prompt` | `hookSpecificOutput.additionalContext` |
| `PreToolUse` | `tool_name`, `tool_input` | `hookSpecificOutput.permissionDecision: "deny"` + `permissionDecisionReason`; `hookSpecificOutput.updatedInput` (rewrite) |
| `PostToolUse` | `tool_name`, `tool_input`, `tool_response` | `hookSpecificOutput.additionalContext` |
| `Stop` | `stop_hook_active` | top-level `{"decision": "block", "reason": "…"}` |

`tool_input` is the Claude shape: `Bash → {command}`, `Read → {file_path}`,
`Write → {file_path, content}`, `Edit → {file_path, old_string, new_string}`,
`Grep → {pattern, path}`, `Glob → {pattern, path}`. When the native edit call
carries several edits (pi's `edits[]`), `Edit` additionally carries
`edits: [{old_string, new_string}, …]` and the flat fields describe the first
one; a rewrite that returns `edits` replaces the whole list, a rewrite that
returns only the flat fields rewrites the first. `tool_response` for
`PostToolUse` is the tool's text output as a string, else the native result
serialized as JSON.

## Event mapping

| Claude event | pi seam | dsh seam | Fidelity |
|---|---|---|---|
| `SessionStart` | `session_start` | `session/created` | full |
| `UserPromptSubmit` | `before_agent_start` (inject a message) | `systemPrompt.context` provider evaluated per assembly | full |
| `PreToolUse` | `tool_call` (block or rewrite) | `tools/pre-execute` (deny; **rewrite becomes a deny whose reason carries the intended input**) | **degraded on dsh: no rewrite** |
| `PostToolUse` | `tool_result` | `tools/post-execute` | full |
| `Stop` | `agent_settled` — observe; a `block` becomes `sendUserMessage(reason)` | `agent/turn-stopping` — `agent.steer(reason)` makes refusal real | **degraded on pi** |

dsh 0.1.1 freezes `exec.arguments` before the pre-execute waterfall and its
`PreToolDecision` has no rewrite variant, so a hook's `updatedInput` cannot be
applied. The runner tries in place when the object is not frozen (a future dsh
may allow it) and otherwise **denies** with a reason that states the input the
hook wanted, so the model can re-issue the corrected call. Running the original
command instead would silently discard the hook's intent, and stderr reaches no
one at runtime.

Tool-name translation (native → Claude): pi `bash→Bash read→Read write→Write
edit→Edit grep→Grep find/glob→Glob`; dsh `bash→Bash read→Read write→Write
edit→Edit grep→Grep glob→Glob`. Everything else keeps its native name.

## Corpus

`corpus.json` is a list of cases. Each case gives the manifest, the native
event as each harness would see it, and the expected outcome. A runner's test
suite loads every case whose `harness` list includes it, feeds the native event
through the runner's mapping with the fixture script actually executed, and
asserts the outcome:

- `outcome` (or `outcome_by_harness: {pi: …, dsh: …}` when they differ): `allow` (unchanged), `deny` (with `reason` containing the given
  substring), `rewrite` (with `updatedInput`), `context` (with the given
  `additionalContext` substring), `stop-block` (with `reason`), or
  `failed-open` (proceeds AND a line containing `hook-runner` on stderr).
- `stdin` (or `stdin_by_harness`) lists key/value pairs the fixture must have
  received, proving the translation happened. Every fixture writes the event it
  saw to the path in `HOOK_CONTRACT_ECHO`, so a test asserts stdin without
  altering the handler list.
- `SessionStart` on dsh: `session/created` is a synchronous emit, so the runner
  gathers the context there and delivers it on the first prompt assembly.

Fixtures are Python 3 stdlib scripts so the corpus runs anywhere the harness runs.

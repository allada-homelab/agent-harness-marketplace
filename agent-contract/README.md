> **The executable corpus lives in the maintainer's harness layer** (private),
> beside the two agent bridges, exactly as the hook corpus does. This file is
> the author-facing contract: what a module's `agents/*.md` may contain and how
> each field maps onto pi and dsh. `fields.json` beside this file is what
> `bin/check.sh` validates a module's agent files against.

# The agent contract

A module ships subagent definitions as `agents/<name>.md` in Claude Code's
shape. Claude reads the directory natively as `<plugin>/agents/` and addresses
each one as `<module>:<name>` in its Agent tool. On pi and dsh a generic bridge,
installed as harness foundation, discovers the same files and exposes them
through one `delegate_agent` tool whose `agent_type` takes the same
`<module>:<name>` string. A skill therefore names an agent once and it resolves
on all three harnesses.

Why Claude's shape: among the harnesses with file-based subagents (Claude Code,
Gemini CLI, Cursor, Copilot, OpenCode, Kiro) the file is Markdown with
`name`/`description`/`tools`/`model` frontmatter and a body that is the system
prompt; Cursor reads `.claude/agents/*.md` verbatim. No cross-vendor standard
exists and the Agent Plugins spec declares agents client-specific, so this
contract is the field intersection.

## Manifest

```markdown
---
name: code-explorer
description: Deeply analyzes existing codebase features by tracing execution paths ...
tools: Glob, Grep, LS, Read, WebFetch
model: sonnet
color: yellow
---
You are an expert code explorer. ...
```

| Field | Rule |
|---|---|
| filename | `<name>.md`, kebab-case. **The filename is the identity.** A frontmatter `name` that disagrees with it fails the check. |
| `description` | Required, non-empty. It is what the dispatcher shows the model, so write it to select the agent. |
| `tools` | Optional. Claude's comma-separated string of Claude tool names. Absent means the child inherits every tool. |
| `model` | Optional alias: `sonnet`, `opus`, `haiku` or `inherit`. Bridges resolve it through a configured map or inherit the parent's model. |
| `color`, `permissionMode`, `maxTurns`, `skills`, `memory`, `isolation`, `background`, `effort`, `hooks`, `mcpServers` | Claude-only; carried through and ignored by pi and dsh. |
| body | The child's system prompt. Avoid `{{` pairs: dsh renders personas with a strict template engine, so the bridge rewrites `{{` to `{ {` there. |

## Tools

Claude names translate through the hook contract's table, inverted. A name with
no row is dropped, with one stderr line, so the child's capability set is exact.

| Claude | pi | dsh |
|---|---|---|
| `Bash` | `bash` | `bash` |
| `Read` | `read` | `read` |
| `Write` | `write` | `write` |
| `Edit` | `edit` | `edit` |
| `Grep` | `grep` | `grep` |
| `Glob` | `find` | `glob` |
| `LS` | `ls` | dropped |
| anything else (`WebFetch`, `WebSearch`, `TodoWrite`, `NotebookRead`, `KillShell`, `BashOutput`, `Agent`, `Skill`, MCP tools) | dropped | dropped |

## Per-harness mapping

| Concern | Claude | pi | dsh | Fidelity |
|---|---|---|---|---|
| Dispatch | Agent tool, `subagent_type` | `delegate_agent` → isolated child `pi` process | `delegate_agent` → `ctx.subagents` child session | full |
| System prompt | body | `--append-system-prompt` | `persona` (braces neutralized) | full |
| Tool restriction | `tools` | `--tools` | `toolFilter.allow` | translated set only |
| Model | alias | alias map or inherit | alias map, gated by the session allowlist, or inherit | inherit unless mapped |
| Standing cost | one Agent schema | tool inactive until a module skill is invoked or `/agents` | one schema plus a catalog line per agent | pi ~0 while inactive |
| Background / continuable children | yes | no | not in this version | **degraded** |
| `maxTurns`, `skills`, `memory`, `permissionMode`, `isolation` | native | ignored | ignored | **degraded** |
| Concurrency | harness | 4 in flight, per-child timeout | provider's | pi capped |

## Writing a skill that uses agents

Name the type once (`feature-dev:code-explorer`) and tell the model which tool
dispatches it per harness: the Agent tool on Claude, `delegate_agent` on pi and
dsh, and a sequential inline fallback when neither exists. Give every child a
self-contained prompt; it sees none of the parent conversation. See
`modules/feature-dev/skills/feature-dev/SKILL.md` for the reference phrasing.

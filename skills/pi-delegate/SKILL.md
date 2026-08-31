---
name: pi-delegate
description: Delegate a routine task to the pi.dev coding agent (running on the user's self-hosted open-weight LLM). Use when a task is well-defined and self-contained, when you want to save Anthropic credits/tokens on something simple, or as a fallback when the Anthropic API is down or rate-limited. Pi runs locally with a deliberately lean, injection-audited config (hash-anchored edits, tool repair, MCP proxy, guard extensions — see pi/README.md).
tags: [homelab, delegation]
---

# Pi delegate

Delegate work to [pi.dev](https://pi.dev) (`@earendil-works/pi-coding-agent`) running against the user's self-hosted open-weight LLM at `https://ai-api.internal.devguy.dev/v1`. Pi acts as a sub-agent: it does the requested task in its own session, writes its response to stdout, and exits.

## When to use this skill

Use it when **all** of these are true:

- The task is **routine, well-defined, and self-contained** — clear input → clear output, doesn't require multi-step exploratory reasoning across the codebase.
- The work would **burn meaningful Anthropic tokens** on the main agent (e.g. a long mechanical loop, large-file processing, repetitive transformations).
- **Behavioral parity is sufficient** — the user is OK with the local model's output quality for this specific task.

Or any one of these:

- The Anthropic API is **down, rate-limited, or otherwise unavailable**.
- The user **explicitly asks** to use pi or the local LLM.
- The task **must run offline / on-network-only** (the homelab tunnel is the constraint).

## When NOT to use it

- **Multi-step exploratory work** with shifting context — keep this on the main Claude agent.
- **Architecture-level reasoning** or tasks that benefit from extended thinking — Claude is stronger here.
- **Tasks needing Anthropic-specific features** (claude code skills/commands tied to claude code, claude-specific tooling, etc.).
- **You ARE pi** — if this skill is being auto-loaded into pi itself, it has no effect. Do the task directly. Don't shell out to `pi -p` from inside pi (recursion is wasteful and will cost double the tokens).

## How to invoke

Use the Bash tool. Standard invocation:

```bash
pi -p "<concise task description>"
```

For structured/parseable output:

```bash
pi -p --mode json "<task>"
```

### Model selection

`~/.davidallada-developer-setup/pi/models.json` defines 4 IDs — stable aliases, not fixed models. The backing model behind each alias changes server-side (llama-swap); this doc describes capability ORDERING, not architecture. For which model currently backs which alias, see `~/.davidallada-developer-setup/pi/README.md`'s dated backing-model table — that's the single source of truth, not this skill.

| ID | Relative capability | Thinking |
|---|---|---|
| `large-default:agent` | large | on |
| `large-default:no-think-agent` | large | off |
| `fast-default:agent` | fast | on |
| `fast-default:no-think-agent` | fast | off |

**Base capability.** `large-default` outranks `fast-default` — pick it for non-trivial coding, agentic loops, and multi-step reasoning. `fast-default` trades some capability for speed.

**Thinking mode.** Thinking-on materially beats thinking-off on hard reasoning, math, and complex coding for this class of model. `:no-think-agent` only earns its keep when the task is simple enough that step-by-step deliberation doesn't matter.

All four are bounded by the underlying open-weight model's ceiling, not Claude's — don't delegate anything where the gap to Claude would matter to the user.

**Picking a variant** (most → least capable):

1. **`large-default:agent`** — top quality on this homelab. Non-trivial coding, agentic loops, multi-step refactors, repo-level reasoning, anything where the output matters.
2. **`large-default:no-think-agent`** — dense 27B, no reasoning phase. Faster than #1, still capable for moderate work. Often beats `fast-default:agent` on coding tasks because the larger effective model wins out even without deliberation.
3. **`fast-default:agent`** — MoE with thinking engaged. Lower base capability than `large-default` but reasoning is on. Reasonable for routine work where MoE speed matters and you still need some reasoning.
4. **`fast-default:no-think-agent`** — lowest tier here, but still useful for one-shot transformations where the model doesn't need to deliberate: summarization, extraction, classification, format conversion (JSON↔YAML, logs→structured, etc.), paraphrasing, simple Q&A, boilerplate/scaffolding generation, mechanical refactors with clear rules. **Avoid** for multi-step logic, math, careful coding, debugging, or tasks that require weighing alternatives — disabling reasoning on the smaller base model compounds both weaknesses.

Thinking is selected by the alias suffix, server-side — `--thinking off` is inert against this endpoint. Pin a specific variant per-invocation instead:

```bash
pi -p --model llama-swap/fast-default:no-think-agent "<task>"
```

The default model is set in `~/.davidallada-developer-setup/pi/settings.json`.

To pass file context like the main Claude does with `@`-mentions:

```bash
pi -p @relevant-file.py "<task referencing the file>"
```

To make the call ephemeral, skip the session file with `--no-session`:

```bash
pi -p --no-session "<task>"
```

Sessions are otherwise archived as JSONL transcripts under the configured `sessionDir` (`~/.local/share/pi/sessions`, set in `~/.davidallada-developer-setup/pi/settings.json`) and kept for later export/analysis — so reserve `--no-session` for genuinely throwaway calls; a delegation you might want to review later should keep its session.

## Pi's environment (what it can do)

Pi runs the deliberately lean 2026-08-11 configuration (`~/.davidallada-developer-setup/pi/README.md` is authoritative):

- **Two local guards** (`~/.davidallada-developer-setup/pi/extensions/`): shell-guard (heredocs blocked — put multi-line scripts in a file) and bash-guard (catastrophic bash blocked). No plan-mode, todo, or preset extensions exist anymore.
- **Five pinned packages**: hash-anchored `read`/`edit` (LINE#HASH anchors — edits abort on stale anchors), pi-tool-repair, MCP adapter (coding-only subset — serena, plane, coder; arr/recipes/home-automation/label-gateway are disabled in `~/.davidallada-developer-setup/pi/mcp.json`), statusline, compact-transcript. The adapter is proxy-only via a single `mcp` tool (`mcpScript` is off via `scriptMode:false`). MCP is configured but does **not** attach under `pi -p` — init races the single request (see `~/.davidallada-developer-setup/pi/README.md`) — so never delegate a task needing serena/plane MCP to this skill.
- **No subagents and no slash-command prompts** — they were removed 2026-08-11. Don't tell pi to use a scout/planner/worker or `/commit`-style commands; give it the task directly. For fresh-context review, `pi --print` sub-sessions.
- **No shared skills and no claude-derived system prompt** — pi is self-contained; its only doctrine is the ~20-line `~/.davidallada-developer-setup/pi/APPEND_SYSTEM.md`. Anything pi must know goes in your prompt.

## Output handling

- Pi writes its response to stdout. Capture as a normal Bash tool result.
- For `--mode json`, parse the JSON and surface relevant fields.
- For `--mode text` (default), pass the response back as-is — don't paraphrase pi's output unless the user asks for a summary.
- If pi's response references files it modified, verify they actually changed (pi has its own write tool — it can edit files in-place).

## Failure modes & fallbacks

| Failure | Surface to user, then |
|---|---|
| `pi: command not found` | Surface "pi.dev CLI not installed". Fall back to handling the task in the main Claude session. |
| HTTP 502 / timeout | Surface "homelab LLM unreachable (probably down or off-network)". Fall back to main Claude. |
| Pi returns an error message about model/auth | Surface the exact error. Fall back to main Claude. |
| Pi runs > 2 minutes for a task you expected to be fast | Cancel (`Ctrl+C` if interactive; for the Bash tool, kill the subprocess via the kill_shell pattern) and fall back. |

## Cost / token sense

The point of delegation is to save Anthropic spend on cheap-to-run tasks. Don't delegate something that takes pi 5 minutes and lots of homelab GPU when Claude could finish it in 10 seconds. Delegate when:

- Mechanical work that's "do this loop N times".
- Bulk file edits where the diff is obvious.
- Trivial Q&A that doesn't need full Claude context.

## Examples of good delegation

```bash
# Generate boilerplate test scaffolding
pi -p --no-session "Write pytest scaffolding for src/foo/bar.py with 5 parameterized cases covering happy path, empty input, None, error states, and concurrent calls. Output the test file content only."

# Mechanical refactor
pi -p --no-session "Replace all 'logger.info(\"x=%s\", x)' patterns in src/ with f-string equivalents. Show only the changed lines and their file paths."

# Quick reference lookup (when web search isn't available)
pi -p --no-session --model llama-swap/fast-default:no-think-agent "What's the canonical way to declare a typed dict in Python 3.12 with optional fields?"
```

## Examples of bad delegation (do NOT delegate these)

- "Plan the architecture for a new caching layer across these 5 services" — that's exploratory; main Claude does this better.
- "Review my PR for security issues" — security review benefits from Claude's reasoning depth.
- "Debug this intermittent test failure" — debugging needs context-rich exploration.

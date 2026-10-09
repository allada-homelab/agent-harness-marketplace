---
name: claude-code-best-practices
description: Use when writing, reviewing, or auditing Claude Code configuration or Claude prompts — CLAUDE.md and CLAUDE.local.md, .claude/rules, SKILL.md skills and commands, subagents in .claude/agents, hooks and permissions in settings.json, output styles, plugin.json and marketplace.json, .mcp.json, or system prompts sent to the Claude API. Covers the CC- (configuration) and PROMPT- (API prompting) rule families and a review procedure with severity levels and a report format. The rule format of this library itself lives in meta-best-practices.
---

# Claude Code best practices

A curated rule set for Claude Code configuration (`CC-`) and for prompts
sent to current Claude models through the API (`PROMPT-`). Each rule has
a stable ID and a one-line summary. Full
**What / Why / How / When-not-to-apply** entries live in `references/`.

To audit a configuration — find the files, apply these rules, calibrate
severity and write the report — follow
[`references/review.md`](./references/review.md).

## When to apply this skill

Activate when any of these are true:

- A `CLAUDE.md`, `.claude/rules/` file, `SKILL.md`, `.claude/agents/` file, output style, `settings.json` hook or permission block, `.claude-plugin/plugin.json`, `marketplace.json` or `.mcp.json` is being written, edited, or reviewed.
- The user asks whether a skill, prompt, hook or plugin follows best practices, or asks to review, audit, lint or improve their Claude Code setup.
- A skill doesn't trigger or mis-triggers, Claude ignores CLAUDE.md, or context cost from instructions is too high.
- A system prompt or `messages.create` call for the Claude API is being written or reviewed.
- The user references a `CC-` or `PROMPT-` rule ID.

## How to use the rule index

1. Scan the relevant section(s) below for rule IDs that apply.
2. For each rule you intend to apply or flag, open the corresponding `references/` file and read **only that rule's entry** — they're keyed by ID.
3. Cite the rule ID when you explain a change to the user (e.g. "Moving the release runbook into a skill — CC-014").

## Rules — All instructions

See [`references/instructions.md`](./references/instructions.md).

- **CC-001** — Every line earns its place: cut what Claude can infer from the code, standard conventions, and self-evident advice.
- **CC-002** — Non-obvious constraints state their reason.
- **CC-003** — Say what to do, not only what to avoid — especially for output format.
- **CC-004** — Emphasis (`IMPORTANT`, `MUST`) on at most one or two lines per file; aggressive wording over-triggers on current models.
- **CC-005** — Specific enough to test: name the exact command, file, path or threshold.
- **CC-006** — One term per concept, within a file and across files that load together.
- **CC-007** — No time-conditional statements outside an explicit legacy section.
- **CC-008** — When format matters, three to five diverse, concrete examples in `<example>` tags.
- **CC-009** — Files that load together don't contradict each other.
- **CC-010** — No secrets, credentials or tokens in any instruction file.

## Rules — Choosing the mechanism

See [`references/mechanism.md`](./references/mechanism.md).

- **CC-011** — Choose CLAUDE.md, rule, skill, subagent, hook, output style or plugin by when it needs to load.
- **CC-012** — "Every time X, do Y" is a hook, not prose.
- **CC-013** — "Never do X" is a `PreToolUse` hook, a deny rule or managed settings, not only prose.
- **CC-014** — A procedure longer than about 10 lines moves from CLAUDE.md into a skill.
- **CC-015** — Directory- or file-type-specific guidance goes in a path-scoped rule or a subdirectory CLAUDE.md.
- **CC-016** — Personal preferences stay out of committed project files.
- **CC-017** — API docs, schemas and long reference material stay out of CLAUDE.md.
- **CC-018** — Repeated "be shorter" or format instructions become an output style.

## Rules — CLAUDE.md

See [`references/claude-md.md`](./references/claude-md.md).

- **CC-019** — Each CLAUDE.md under 200 lines; always-loaded files small in total.
- **CC-020** — Include what Claude can't guess (commands, quirks, gotchas); exclude what it can learn from the code.
- **CC-021** — CLAUDE.md is an index; `@path` imports load at launch and don't reduce context cost.
- **CC-022** — Subdirectory CLAUDE.md loads when its directory is touched and is summarized away at compaction.
- **CC-023** — Tell Claude what to preserve when the conversation compacts.
- **CC-024** — A checked-in CLAUDE.md has an owner and is audited with `/doctor` and `/doctor prompt-audit`.

## Rules — Rule files

See [`references/rules.md`](./references/rules.md).

- **CC-025** — Scope rules with `paths:`; an unscoped rule loads in every session like CLAUDE.md.
- **CC-026** — One short concern per rule file.
- **CC-027** — A cross-cutting concern is one path-scoped rule, not copies in several nested CLAUDE.md files.
- **CC-028** — Only unscoped rules and the project-root CLAUDE.md are re-injected after compaction.

## Rules — Skills and commands

See [`references/skills.md`](./references/skills.md).

- **CC-029** — Frontmatter starts on line 1 and parses; malformed YAML silently disables auto-invocation.
- **CC-030** — Frontmatter field names are spelled exactly; unknown fields are silently ignored.
- **CC-031** — `name`: at most 64 lowercase-hyphen characters, no reserved words, not vague; no `synced` or `anthropic-skills` folder.
- **CC-032** — `description`: third person, what and when in the user's words, key use case first, no overlap with other skills.
- **CC-033** — New commands are skill folders, not `.claude/commands/` files.
- **CC-034** — Skills that deploy, commit, push, send, delete or spend set `disable-model-invocation: true`.
- **CC-035** — Background-knowledge skills set `user-invocable: false`.
- **CC-036** — `context: fork` only for self-contained task bodies; mind `background` and its narrower tools.
- **CC-037** — `paths:` limits a skill's auto-activation to matching files.
- **CC-038** — Body under 500 lines with the most important instructions first; compaction keeps only the first 5,000 tokens.
- **CC-039** — Phrase guidance as standing instructions that cover the whole task.
- **CC-040** — Freedom matches risk: exact commands for fragile steps, heuristics for judgment.
- **CC-041** — One default approach with an escape hatch, not a menu.
- **CC-042** — Multi-step workflows get a checklist and a validate-fix-repeat loop.
- **CC-043** — Show the expected output with a template or examples when format matters.
- **CC-044** — Supporting files linked one level deep with what and when; tables of contents over 100 lines.
- **CC-045** — Scripts: say run or read, handle errors, explain constants, state dependencies, use the skill-directory variable.
- **CC-046** — Name MCP tools by their fully qualified, server-prefixed names.
- **CC-047** — Keep `allowed-tools` narrow; a broad grant in a committed skill is a security finding.
- **CC-048** — Injected commands are deterministic, fast and pre-approved; a failure aborts the invocation.
- **CC-049** — At least three evals, each run with the skill on and off.
- **CC-050** — Test triggering in both directions on every model the skill runs on.

## Rules — Subagents

See [`references/subagents.md`](./references/subagents.md).

- **CC-051** — A subagent's description says when to delegate to it.
- **CC-052** — `tools` is the minimum needed; reviewers and researchers are read-only.
- **CC-053** — The body is self-contained; the subagent doesn't see the conversation.
- **CC-054** — The body specifies the return format; only the final message returns.
- **CC-055** — Delegate for isolation or parallelism, not for history-dependent work; damp over-delegation where the model needs it.
- **CC-056** — Review subagents report correctness and requirement gaps, not style.
- **CC-057** — `skills:` preloads full skill content; list only skills the subagent uses.

## Rules — Hooks and permissions

See [`references/hooks.md`](./references/hooks.md).

- **CC-058** — Deterministic behavior is a hook: `PostToolUse`, `PreToolUse` exit 2, `Stop`, `SessionStart`, `PreCompact`.
- **CC-059** — Know the five hook types and every source hooks merge from.
- **CC-060** — Hooks are fast; `/doctor` flags slow ones.
- **CC-061** — Hook input is untrusted: quote and validate it, never interpolate it unquoted into a shell.
- **CC-062** — Hook output is minimal; it lands in Claude's context.
- **CC-063** — A `Stop` hook gives a clear message and a realistic way to pass.
- **CC-064** — Allow specific commands, deny sensitive paths, sandbox for autonomy, managed settings for org-wide guardrails.
- **CC-065** — Unattended `claude -p` runs use `--permission-mode dontAsk` with explicit `--allowedTools`.

## Rules — Output styles

See [`references/output-styles.md`](./references/output-styles.md).

- **CC-066** — A custom output style drops the coding instructions unless it sets `keep-coding-instructions: true`.
- **CC-067** — Keep `--append-system-prompt` short.

## Rules — Plugins and marketplaces

See [`references/plugins.md`](./references/plugins.md).

- **CC-068** — Manifest in `.claude-plugin/`; component folders at the plugin root.
- **CC-069** — Make a plugin only to share a setup across repositories or people.
- **CC-070** — Every enabled plugin's skill, agent and command descriptions cost context every turn.
- **CC-071** — Plugin paths use the plugin-root variable; state that survives updates uses the plugin-data variable.
- **CC-072** — Plugin skills are namespaced `/plugin:skill`.
- **CC-073** — `claude plugin validate` passes and `claude plugin eval` gates CI against its no-plugin baseline.
- **CC-074** — A plugin runs as the user: minimal hooks, no needless network calls, no secrets.
- **CC-075** — Marketplaces have `marketplace.json` and versioned releases.

## Rules — MCP servers

See [`references/mcp.md`](./references/mcp.md).

- **CC-076** — Prefer an installed CLI where it covers the need.
- **CC-077** — Disconnect unused MCP servers; check per-tool cost with `/context all`.
- **CC-078** — Pair each MCP server with a skill that teaches how to use it.
- **CC-079** — No secrets in a committed `.mcp.json`; know that scopes override rather than merge.

## Rules — API prompts

See [`references/prompts.md`](./references/prompts.md).

- **PROMPT-001** — Pass the colleague test.
- **PROMPT-002** — XML tags separate instructions, context, examples and inputs; long documents first, query last.
- **PROMPT-003** — No prefilled final assistant turn; it returns a 400 from the 4.6 models on.
- **PROMPT-004** — Adaptive thinking and `effort`; `budget_tokens` returns a 400 from 4.7 on.
- **PROMPT-005** — Opus 5.5: thinking always on, start at `medium` effort, leave `max_tokens` headroom.
- **PROMPT-006** — Don't ask for reasoning in the response; read summarized thinking.
- **PROMPT-007** — Remove legacy steering the target model's guidance names: aggressive tool prompting, and model-specific verification and "think carefully" lines.
- **PROMPT-008** — Tune verbosity and progress updates per model.
- **PROMPT-009** — Change effort per message; a top-level change invalidates the cache.
- **PROMPT-010** — Keep history append-only; use mid-conversation system messages.
- **PROMPT-011** — Wrap pasted content in `<pasted_content>` tags with a random ID, explained in the system prompt.
- **PROMPT-012** — Say whether to act or advise.
- **PROMPT-013** — Require confirmation before destructive, irreversible or visible actions; forbid `--no-verify`.
- **PROMPT-014** — Keep scope minimal; validate only at system boundaries.
- **PROMPT-015** — Ask for a general solution; never hard-code to tests.
- **PROMPT-016** — Investigate before answering; never speculate about unopened code.
- **PROMPT-017** — Clean up temporary files.
- **PROMPT-018** — Keep long-horizon state in files and git.
- **PROMPT-019** — A text-only `end_turn` is not completion; nudge on open items, at most two or three times.
- **PROMPT-020** — Parallel tool calls for independent operations; never guess parameters.

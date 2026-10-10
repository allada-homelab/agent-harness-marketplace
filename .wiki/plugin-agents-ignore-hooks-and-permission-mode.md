---
type: gotcha
title: Plugin agents ignore hooks, mcpServers and permissionMode
description: Claude Code ignores hooks, mcpServers and permissionMode in plugin agent frontmatter, so a module agent's limits must be enforced by the skill that dispatches it.
tags: [modules, skills]
generated: {by: okf-wiki/haiku, at: 2026-10-10T03:06:49Z}
verified:
  - {by: okf-wiki/haiku, at: 2026-10-10T03:06:49Z, commit: 8d8078a913ef}
sources:
  - {resource: https://code.claude.com/docs/en/sub-agents, id: s1}
  - {resource: modules/okf-wiki/skills/wiki/SKILL.md, id: s2}
---

# Plugin agents ignore hooks, mcpServers and permissionMode

## Symptom

A module agent that should be limited (the okf-wiki scribe may only write under `.wiki/`) runs with no enforcement. Adding a `PreToolUse` hook or `permissionMode` to its frontmatter looks like it works, but nothing is blocked.

## What fails

Claude Code's sub-agents docs say that for security reasons plugin subagents do not support the `hooks`, `mcpServers` or `permissionMode` frontmatter fields, and that they are ignored when loading agents from a plugin[^s1]. An audit proposed a `PreToolUse` hook for the scribe; it would have been silently dropped.

## What works

The dispatching skill enforces the limit. It runs `git status --porcelain` before and after the scribes and commits only `.wiki/` paths[^s2]. The only per-agent limit a module can declare is the `tools:` list.

## Why

Plugin agents are loaded from the plugin, not from a trusted local config, so Claude Code strips the fields that could widen their power. Any guard has to sit in code the main session controls.

## Verify

- `modules/okf-wiki/skills/wiki/SKILL.md` :: `Dispatching the okf-wiki agents`

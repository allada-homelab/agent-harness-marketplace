---
name: code-simplifier
description: Simplify recently changed code for clarity, consistency and maintainability without changing what it does. Dispatches the code-simplifier agent over the uncommitted changes by default, or over the files, diff or branch given as arguments; it edits in place, follows the project's CLAUDE.md / AGENTS.md conventions, and reports what changed. Use after writing or modifying code, or when asked to simplify, clean up, refine or tidy code; not for finding bugs or reviewing a pull request.
user-invocable: true
argument-hint: "[files, a diff ref, or a scope description]"
tags: [refactor, quality]
---

# Code simplifier

Simplify the code in scope for clarity, consistency and maintainability while
preserving its exact functionality. Scope: $ARGUMENTS — when none is given,
the uncommitted changes in the working tree (`git status`, `git diff`), or if
the tree is clean, the current branch's changes against the default branch.

## Agent

One agent ships beside this skill, type `code-simplifier:code-simplifier`.
Dispatch it with whatever this harness has:

- **Claude Code**: the Agent tool with `subagent_type` set to the type above.
- **pi and dsh**: the `delegate_agent` tool with `agent_type` set to the type
  above. On pi the tool is inactive until this skill is invoked; if it is
  missing, run `/agents` once.
- **No delegation tool at all**: do the work yourself using the agent's body
  as your brief. The definition is in `./../../agents/code-simplifier.md`
  beside this skill.

The child sees none of this conversation. Give it the scope explicitly — the
list of files, the diff ref, or the exact instruction it should resolve with
`git` — plus any constraint the user stated (a file to leave alone, a
convention to keep).

## Steps

1. Resolve the scope to concrete files or a diff ref and state it in one line.
2. Dispatch `code-simplifier:code-simplifier` with that scope.
3. Relay its report: files changed, the significant refinements, and any
   out-of-scope issue it flagged. Do not commit; the user reviews the diff.

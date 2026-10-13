---
type: gotcha
title: Untrusted worktree agent CLIs need more than a permission mode
description: A permission mode alone does not isolate an agent CLI run on untrusted PR content; claude -p and codex exec each need extra isolation flags.
tags: [claude-p, injection, worktree]
generated: {by: okf-wiki/haiku, at: 2026-10-13T23:16:26Z}
verified:
  - {by: okf-wiki/haiku, at: 2026-10-09T17:24:51Z, commit: 08add093dd31}
  - {by: okf-wiki/haiku, at: 2026-10-13T23:16:26Z, commit: d5ec0074c310}
sources:
  - {resource: https://code.claude.com/docs/en/permission-modes, id: s1}
  - {resource: https://code.claude.com/docs/en/permissions, id: s2}
  - {resource: https://code.claude.com/docs/en/settings-reference, id: s3}
  - {resource: https://code.claude.com/docs/en/cli-reference, id: s4}
  - {resource: https://developers.openai.com/codex/noninteractive, id: s5}
  - {resource: https://developers.openai.com/codex/config-reference, id: s6}
---

# Untrusted worktree agent CLIs need more than a permission mode

## Symptom

A reviewer run on a PR worktree under `bypassPermissions` with a deny-list let `curl` reach example.com and read a planted secret file outside the worktree into its output (local repro, 2026-10-09). Switching only the permission mode to `dontAsk` would not close the read path, per the docs below.

## What fails

Claude `dontAsk` auto-runs built-in read-only Bash (`cat`, `head`, read-only git) on any path [^s1][^s2]. It also honors allow rules from the user's settings and the worktree's own `.claude/settings.json`, and a project skill's `allowed-tools` is not gated by workspace trust in `-p` runs.

Codex's read-only sandbox is network-off, but app/connector traffic and MCP tool calls are not governed by it [^s5][^s6]. User config brings MCP servers, and a trusted project's `.codex/` execpolicy rules can run commands outside the sandbox.

## What works

Claude: `--permission-mode dontAsk`, `--settings '{"permissions":{"blockReadsOutsideWorkingDirectories":true}}'` [^s3], `--setting-sources ""`, `--strict-mcp-config`, `--tools "Read,Grep,Glob,Bash"` (drops Skill, WebFetch and Agent) [^s4], and an `--allowedTools` list that admits Bash only for `git diff|show|log|blame`. Readable dirs are the run dir plus, for this side only, any optional context repos passed as `--add-dir`. Repro: denied `curl`, `cat` and Read on the secret; `git log` and worktree reads still worked.

Codex: `--ignore-user-config`, `--ignore-rules`, `-c approval_policy="never"`, `-c features.apps=false`, `-c web_search="disabled"`, `-c shell_environment_policy.inherit="core"` [^s6]. Bogus values for these keys are rejected at config load, so they are parsed. The sandbox is `read-only` only when bubblewrap works; inside a container the script falls back to `danger-full-access` (so the flags above are the only isolation there), and on a host without bubblewrap it refuses to start rather than fall back.

## Why

The permission mode only governs prompts. Read-only built-ins, workspace-supplied settings and skills, user config and app or MCP traffic sit outside it. Stripping those sources is what makes a PR's content unable to steer the reviewer.

## Verify

- `modules/dual-agent-pr-review/skills/dual-agent-pr-review/scripts/dual_review.sh` :: `claude_iso`
- `modules/dual-agent-pr-review/skills/dual-agent-pr-review/scripts/dual_review.sh` :: `codex_sandbox_mode`

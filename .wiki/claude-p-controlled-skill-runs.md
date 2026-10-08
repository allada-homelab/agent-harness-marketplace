---
type: gotcha
title: Controlled headless claude -p runs for skill measurement
description: "Measure a skill instruction with claude -p --tools '' --strict-mcp-config and no --bare: without strict MCP, an auth-reminder leaks into output; --bare fails under OAuth login."
tags: [skills, evals, claude-p]
generated: {by: okf-wiki/sonnet, at: 2026-10-08T05:13:19Z}
verified:
  - {by: okf-wiki/sonnet, at: 2026-10-08T05:13:19Z, commit: edd5fec2d9b9}
sources:
  - {id: s1, resource: modules/ste-writing/README.md, title: "How the instruction was chosen: the measurement these flags produced"}
---

# Controlled headless claude -p runs for skill measurement

## Symptom

Comparing instruction variants with headless `claude -p` gave noisy or broken
runs. Several judged outputs ended with a stray "connectors need authorization"
paragraph that the blind judge counted as an error.[^s1] A `--bare` run returned
`{"is_error":true,"result":"Not logged in · Please run /login"}`.

## What fails

- Omitting `--strict-mcp-config`: the "MCP servers require authentication"
  system reminder reaches the model and leaks into its output.
- `--bare`: it restricts auth to `ANTHROPIC_API_KEY` or `apiKeyHelper`, so it
  fails under the fleet's OAuth login.

## What works

```
claude -p --tools "" --no-session-persistence --setting-sources "" \
  --disable-slash-commands --strict-mcp-config --model <m> \
  --output-format json [--append-system-prompt <variant>] <prompt>
```

With `--strict-mcp-config` a probe asking the model to list the MCP servers in
its system prompt answered NONE, and the stray paragraph disappeared.

## Why

The other flags strip ambient state (tools, session history, settings, slash
commands) so only the variant under test differs. Verified 2026-10-08 on Claude
Code 2.1.293 across 3 rounds and 336 runs on Sonnet and Haiku. Cost was about
12 s and 1k output tokens per prose task on Sonnet at `-j7` parallelism. Note
that `--model haiku` resolved to `claude-haiku-5-5` (the `modelUsage` key), not
Haiku 4.5, so name the model explicitly if the tier matters.

## Verify

- `modules/ste-writing/README.md` :: `How the instruction was chosen`

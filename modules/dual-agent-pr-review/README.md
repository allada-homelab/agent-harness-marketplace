# dual-agent-pr-review

Review a GitHub PR with Claude Code and Codex in parallel, then reconcile their findings into one
consensus set. Ships the `dual-agent-pr-review` skill (`/dual-agent-pr-review` on Claude Code):
runs two independent CLI reviewers over the same PR snapshot, builds a Venn of agreed / claude-only
/ codex-only findings, runs reconciliation rounds on the disagreements, and verifies every survivor
against the code before reporting. Requires the `claude`, `codex`, `gh`, and `jq` CLIs on `PATH`.

This module is claude-only.

## Install

- Claude Code: `/plugin marketplace add allada-homelab/agent-harness-marketplace` then
  `/plugin install dual-agent-pr-review@agent-harness-marketplace`

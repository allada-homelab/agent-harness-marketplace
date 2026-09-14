# feature-dev

A comprehensive, structured 7-phase workflow for building new features with
specialized agents for codebase exploration, architecture design, and quality
review.

Instead of jumping straight into code, the workflow guides you through
understanding the codebase, asking clarifying questions, designing architecture,
and ensuring quality — resulting in better-designed features that integrate
seamlessly with your existing code.

## Contents

- `skills/feature-dev/SKILL.md` — the 7-phase workflow: discovery, codebase
  exploration, clarifying questions, architecture design, implementation, quality
  review, and summary.

## Harnesses

Claude-only (scoped `harness: [claude]`). The workflow describes Claude Code's
`/feature-dev` command and its `code-explorer`, `code-architect` and
`code-reviewer` agents, so it is excluded from the pi and dsh manifests.

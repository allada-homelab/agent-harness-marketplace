---
name: repo-best-practices
description: Use when editing repository hygiene and CI config — .pre-commit-config.yaml hooks, .github/dependabot.yml, GitHub Actions workflows (.github/workflows/*.yml, permissions, zizmor audits), CODEOWNERS, justfile task-runner recipes that CI calls, or secret scanning (gitleaks). Covers the REPO- rule family (pre-commit as a maintained artifact, one dependency bot with a cooldown, secret scanning, justfile/CI parity, CODEOWNERS, workflow static analysis, least-privilege GITHUB_TOKEN). Language-agnostic repo plumbing; language rules live in the language skills.
---

# Repository best practices

A curated rule set for the plumbing around a codebase: commit hooks,
dependency-update bots, task runners, review routing and GitHub Actions
workflow security. Each rule has a stable ID and a one-line summary. Full
**What / Why / How / When-not-to-apply** entries live in `references/`.

Language-level lint and tool rules live in the language skills — for
example [`python-best-practices`](../python-best-practices/SKILL.md) and
[`uv-best-practices`](../uv-best-practices/SKILL.md).

## When to apply this skill

Activate when any of these are true:

- You're editing or reviewing `.pre-commit-config.yaml`, `.github/dependabot.yml`, `.github/CODEOWNERS`, a `justfile`, or any `.github/workflows/*.yml`.
- The user asks about pre-commit hooks, Dependabot (cooldowns, ecosystems, auto-merge), secret scanning (gitleaks), keeping local checks and CI in sync, code-owner review, zizmor, or `permissions:` / `GITHUB_TOKEN` scopes.
- The user references a `REPO-` rule ID.

## How to use the rule index

1. Scan the relevant section(s) below for rule IDs that apply to the current file.
2. For each rule you intend to apply or flag, open the corresponding `references/` file and read **only that rule's entry** — they're keyed by ID.
3. Cite the rule ID when you explain a change to the user.

## Rules — Hooks, bots and review routing

See [`references/hooks-and-bots.md`](./references/hooks-and-bots.md).

- **REPO-001** — Treat `.pre-commit-config.yaml` as a first-class artifact: SHA-pinned remote hooks, local hooks running the project's own tools, a why-comment on every hook.
- **REPO-002** — One dependency bot (Dependabot) maintains every pin — lockfile, actions, pre-commit revs, dev container Features — with a cooldown and no auto-merge.
- **REPO-004** — Secret-scan the repo itself (gitleaks, detect-secrets or trufflehog) on every commit.
- **REPO-007** — Every CI step is a `just` recipe, `just check` runs them all, and a test enforces the parity and `just --list` help text.
- **REPO-008** — Keep a `CODEOWNERS` file for review routing.

## Rules — GitHub Actions

See [`references/github-actions.md`](./references/github-actions.md).

- **REPO-009** — Statically audit workflows with zizmor (injection, over-broad permissions, persisted credentials, unpinned actions).
- **REPO-010** — Start workflows from `permissions: {}` and grant each job only the `GITHUB_TOKEN` scopes it needs.

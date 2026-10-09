---
name: skills-best-practices
description: Use when writing, reviewing, or restructuring an Agent Skill — a SKILL.md file, its name and description frontmatter, its reference files, or the scripts it bundles — or when a skill fails to trigger, triggers on the wrong prompts, loads too much context, or needs evaluations. Covers the SKILL- rule family (discovery, structure, content, workflows, scripts, evaluation), drawn from Anthropic's skill-authoring best-practices guide. The rule format of this library itself lives in meta-best-practices.
---

# Skills best practices

A curated rule set for authoring Agent Skills (`SKILL.md` plus its bundled
files). Each rule has a stable ID and a one-line summary. Full
**What / Why / How / When-not-to-apply** entries live in `references/`.

Source: Anthropic's
[Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices).
Where a rule departs from the guide, its entry says so. The format rules of
this library (rule IDs, the four-part entry) live in
[`meta-best-practices`](../meta-best-practices/SKILL.md).

## When to apply this skill

Activate when any of these are true:

- A `SKILL.md` file, or a file a skill bundles (a reference file, a script), is being written, edited, or reviewed.
- The user asks how to write a skill's `name` or `description`, how to split a long skill, or how to structure its reference files.
- A skill does not trigger when expected, triggers on unrelated prompts, or misses or ignores its bundled files.
- The user asks how to test or evaluate a skill, or how to iterate on one.
- The user references a `SKILL-` rule ID.

## How to use the rule index

1. Scan the relevant section(s) below for rule IDs that apply to the current skill.
2. For each rule you intend to apply or flag, open the corresponding `references/` file and read **only that rule's entry** — they're keyed by ID.
3. Cite the rule ID when you explain a change to the user (e.g. "Moving the API tables into a reference file — SKILL-006").

## Rules — Discovery (name and description)

See [`references/discovery.md`](./references/discovery.md).

- **SKILL-001** — `name`: at most 64 characters, lowercase letters, digits and hyphens only, no XML tags, no reserved words (`anthropic`, `claude`).
- **SKILL-002** — Name skills in one consistent pattern (gerund form preferred); never vague (`helper`, `utils`) or generic (`data`, `files`).
- **SKILL-003** — `description` states what the skill does *and* when to use it, with the concrete terms a matching prompt contains; non-empty, at most 1,024 characters, no XML tags.
- **SKILL-004** — Write the `description` in the third person; never "I can…" or "You can…".

## Rules — Structure and progressive disclosure

See [`references/structure.md`](./references/structure.md).

- **SKILL-005** — Add only context the model does not already have; every paragraph must justify its token cost.
- **SKILL-006** — Keep the `SKILL.md` body under 500 lines; move detail into reference files that `SKILL.md` names and loads on demand.
- **SKILL-007** — Link every reference file directly from `SKILL.md`; never chain references more than one level deep.
- **SKILL-008** — Open any reference file longer than 100 lines with a table of contents.
- **SKILL-009** — Name bundled files for their content, organize them by domain, and write paths with forward slashes.

## Rules — Content

See [`references/content.md`](./references/content.md).

- **SKILL-010** — Match the degree of freedom to the task's fragility: prose for judgment calls, exact commands for fragile sequences.
- **SKILL-011** — Give one default approach with an escape hatch, not a menu of equivalent options.
- **SKILL-012** — No time-conditional instructions; put deprecated methods in a collapsed "old patterns" section.
- **SKILL-013** — Pick one term per concept and use it everywhere in the skill.
- **SKILL-014** — Give an output template, and state how strictly it must be followed.
- **SKILL-015** — Show concrete input/output examples when output style matters; never abstract ones.

## Rules — Workflows and feedback loops

See [`references/workflows.md`](./references/workflows.md).

- **SKILL-016** — Break a complex task into numbered steps with a copyable progress checklist, and make each decision point an explicit branch.
- **SKILL-017** — Build a feedback loop into quality-critical work: validate, fix, re-validate, and proceed only on a pass.
- **SKILL-018** — For batch, destructive or high-stakes operations, have the model write a plan file and validate it before executing (plan-validate-execute).

## Rules — Bundled scripts

See [`references/scripts.md`](./references/scripts.md).

- **SKILL-019** — Scripts handle their expected error conditions with specific, actionable messages instead of punting a raw traceback to the model.
- **SKILL-020** — No unexplained constants in scripts; justify every timeout, retry count and threshold in a comment.
- **SKILL-021** — Ship a utility script for any deterministic operation, and say whether the model should run it or read it.
- **SKILL-022** — List every package a skill needs and how to install it; never assume it is present.
- **SKILL-023** — Refer to MCP tools by their fully qualified, server-prefixed name.

## Rules — Evaluation and iteration

See [`references/evaluation.md`](./references/evaluation.md).

- **SKILL-024** — Build at least three evaluations from observed failures, and measure a no-skill baseline, before writing extensive content.
- **SKILL-025** — Test the skill with every model tier that will run it.
- **SKILL-026** — Iterate by watching a fresh agent use the skill on real tasks: what triggers, what it reads, what it misses, what it ignores.

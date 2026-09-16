# code-review

Automated pull-request review on every harness. Ships the `code-review` skill
(`/code-review` on Claude Code and dsh, `/skill:code-review` on pi) and three
subagents it dispatches — `code-review:triage`, `code-review:reviewer`,
`code-review:scorer` — through the Agent tool on Claude Code and
`delegate_agent` on pi and dsh.

What a run does:

1. a triage agent checks the pull request is worth reviewing
   (open, not a draft, not automated, not already reviewed), lists the
   project's guideline files (`CLAUDE.md`, `AGENTS.md`) and summarizes the change;
2. five reviewers run in parallel, one lens each — guideline
   compliance, shallow bug scan, git history, prior pull-request comments,
   in-code comment guidance;
3. a scorer rates every candidate 0-100 against a fixed rubric and
   anything under 80 is dropped;
4. eligibility is re-checked, then one comment is posted with `gh pr comment`,
   every issue linked by full commit SHA. Nothing survives, nothing is posted.

It is read-only apart from that single comment: it never edits files and never
runs builds or tests. Requires the `gh` CLI, authenticated.

## Install

- Claude Code: `/plugin marketplace add allada-homelab/agent-harness-marketplace`
  then `/plugin install code-review@agent-harness-marketplace`
- pi: install the marketplace package; the skill is globbed in by the root
  manifest.
- dsh: add the bundle; the harness's skills and agents bridges discover the
  skill and the three agents.

## Provenance

A port of the `code-review` plugin from
`anthropics/claude-plugins-official` (MIT). What changed to make it portable:

- the `allowed-tools` restriction became prose (dsh drops the key silently);
- the inline "use a Haiku / Sonnet agent" instructions became three
  `agents/*.md` files with no `model` key: the module is model-agnostic and
  every child inherits the session's model on all three harnesses;
- guideline discovery covers `AGENTS.md` as well as `CLAUDE.md`;
- the review target is `$ARGUMENTS` (a number or URL) with the current
  branch's pull request as the default;
- the comment footer no longer names a harness.

The five lenses, the scoring rubric, the 80 threshold, the double eligibility
check and the permalink rules are unchanged.

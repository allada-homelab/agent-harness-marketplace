# code-review

Automated pull-request review on every harness. Ships the `code-review` skill
(`/code-review` on Claude Code and dsh, `/skill:code-review` on pi) and three
subagents it dispatches — `code-review:triage`, `code-review:reviewer`,
`code-review:scorer` — through the Agent tool on Claude Code and
`delegate_agent` on pi and dsh.

What a run does:

1. a triage agent checks the pull request is worth reviewing
   (open, not a draft, not automated, not already reviewed), sizes the diff,
   lists the project's guideline files (`CLAUDE.md`, `AGENTS.md`) and
   summarizes the change;
2. a **size gate** picks the tier: under 50 changed lines, or every changed
   path documentation or generated (a lockfile, a `linguist-generated` path),
   is **small** — everything else is **normal**;
3. **small** dispatches one combined reviewer covering all five lenses, which
   scores each issue it keeps itself; **normal** dispatches five reviewers in
   parallel, one lens each — guideline compliance, shallow bug scan, git
   history, prior pull-request comments, in-code comment guidance — then one
   scorer batch-rates every candidate the five of them raised, 0-100 against
   a fixed rubric; either way, anything under 80 is dropped;
4. eligibility is re-checked, then one comment is posted with `gh pr comment`,
   every issue linked by full commit SHA. Nothing survives, nothing is posted.

Every reviewer and scorer works under a 25-tool-call budget and skips
generated files outright, so a large or generated-heavy diff degrades to a
partial result instead of an open-ended scan.

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
- the comment footer no longer names a harness;
- added a size gate (a small or generated-only change gets one combined
  reviewer with inline scoring instead of the full fan-out), batch scoring
  (one scorer dispatch per review instead of one per candidate issue), and a
  25-tool-call budget plus a generated-file skip on every reviewer and scorer
  — upstream's five-lens-plus-per-candidate-scorer shape had no size or cost
  bound, and a small or docs-only pull request paid for it in full.

The five lenses, the scoring rubric, the 80 threshold (it gates only whether
an issue is posted, never whether a fix is mandatory), the double eligibility
check and the permalink rules are unchanged.

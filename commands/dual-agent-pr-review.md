---
description: Review a GitHub PR with two independent CLI reviewers (Claude Code and Codex) in parallel, then reconcile their findings into one evidence-backed consensus set.
argument-hint: "<PR url or number> [— review instructions] [claude:<model>/<effort>] [codex:<model>/<effort>]"
allowed-tools: Read, Grep, Glob, Bash, Write, Edit, WebFetch
harness: [claude]
---

# /dual-agent-pr-review

Run the dual-agent review over `$ARGUMENTS`.

Two reviewers with different training and different blind spots read the same diff
independently, then argue their disagreements to a verdict. What survives is the
deliverable. The value is in the **disagreements**, not the overlap: findings both
agents report are usually the obvious ones, while findings only one reports are half
the best catches of the run and half confident nonsense — the reconciliation rounds
are how you tell which.

## Read the workflow first

The full procedure — every step, the exact commands, the docket rules for each
reconciliation round, and the failure modes — lives in:

**`~/.agents/lib/dual-agent-pr-review/WORKFLOW.md`**

Read that file now and follow it. Do not work from memory of it; it is the
authority on the run, and its brief templates and schemas sit beside it under
`~/.agents/lib/dual-agent-pr-review/`.

## Parsing `$ARGUMENTS`

- The PR is a full URL or a bare number. If no PR is given, ask for one — everything
  else has a defensible default, this does not.
- Everything after an em/en dash or `--` is the user's review instruction. Pass it
  through **verbatim** as `--task`; it shapes both reviews identically.
- `claude:<model>/<effort>` and `codex:<model>/<effort>` set each reviewer
  independently, e.g. `claude:opus/high codex:gpt-5.6-sol/xhigh`. Either half may be
  omitted (`codex:/xhigh`). Defaults: `opus`/`high` and `gpt-5.6-sol`/`high`.
- If no models or effort are named, use the defaults and say which you used — do not
  ask.

## Non-negotiables

- **You are the judge, not a third reviewer.** Orchestrate, pair, and verify. Adding
  your own findings to the pool corrupts the comparison. If you spot something both
  reviewers missed, keep it out of the Venn and report it separately, labelled as
  yours.
- **Do not favor the Claude reviewer.** When the two disagree, open the code and
  decide from the code.
- **No finding reaches the user unverified.** Open the cited `file:line` for every
  survivor yourself. A reviewer's CONFIRM is a hypothesis, not proof.
- **A reviewer that ran no commands read no code.** The script rejects those rounds.
  Never use the output anyway because it looks plausible.
- **Both reviews run in the background** (`run_in_background: true`) — a real review
  takes 5–20 minutes and will blow past a foreground timeout.

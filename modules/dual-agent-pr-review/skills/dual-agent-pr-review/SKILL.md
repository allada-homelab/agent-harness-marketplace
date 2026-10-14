---
name: dual-agent-pr-review
description: Review a GitHub PR with two independent CLI reviewers (Claude Code and Codex) in parallel, then reconcile their findings into one evidence-backed consensus set.
argument-hint: "<PR url or number> [— review instructions] [claude:<model>/<effort>] [codex:<model>/<effort>] [no-post]"
allowed-tools: Read, Grep, Glob, Bash, Write, Edit, WebFetch
user-invocable: true
disable-model-invocation: true
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

**`${CLAUDE_SKILL_DIR}/WORKFLOW.md`**

Read that file now and follow it. Do not work from memory of it; it is the
authority on the run, and its brief templates and schemas sit beside it under
`${CLAUDE_SKILL_DIR}/`.

## Parsing `$ARGUMENTS`

- The PR is a full URL or a bare number. If no PR is given, ask for one — everything
  else has a defensible default, this does not.
- Everything after an em/en dash or `--` is the user's review instruction. Pass it
  through **verbatim** as `--task`; it shapes both reviews identically.
- `claude:<model>/<effort>` and `codex:<model>/<effort>` set each reviewer
  independently, e.g. `claude:opus/high codex:gpt-6.1-sol/xhigh`. Either half may be
  omitted (`codex:/xhigh`). Defaults: `opus`/`high` and `gpt-6.1-sol`/`high`.
- If no models or effort are named, use the defaults and say which you used — do not
  ask.
- "Re-review" (or a PR with an earlier run under `~/.claude/dual-review/runs/`) means
  `prepare --since <that run dir>`, still with both reviewers.
- A path to a sibling repository the PR depends on goes to `--context-repo`.
- `no-post` (or "don't post", "just show me") turns off Step 8's default of posting the
  review to someone else's PR; the run then ends with the draft.

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
- **Severity disputes are not yours to settle alone.** A split the rounds did not
  resolve is presented as Unresolved, never quietly downgraded to non-blocking.
- **Broken is blocking, wherever it breaks.** If merging leaves something a user or
  caller will hit that does not work — the PR's own feature or anything else it
  touches — it is blocking, whatever both reviewers labelled it. Use common sense
  about what a user sees, not which line would change.
- **Finish the dual review.** When codex fails, give the fix and re-run that side
  with `run --only codex`; never recommend dropping codex first, never adjudicate its
  side yourself, never hand-edit run files. A single-reviewer result happens only
  when the user chooses it, and is labelled so.
- **Someone else's PR gets the review posted by default** (Step 8), unless the request
  said `no-post`; the user's own PR gets a fix list. Posting never silently drops a
  verified finding: non-blocking ones are posted with a severity · category label
  (e.g. `[Non-blocking · documentation]`), not withheld — and every one is its own
  inline comment.

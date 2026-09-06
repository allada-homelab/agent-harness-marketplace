# Dual-agent PR review — workflow

Referenced by the `dual-agent-pr-review` skill's `SKILL.md`. Nothing auto-loads this
file; the skill must be invoked explicitly (`/dual-agent-pr-review` on Claude Code).

Two reviewers with different training and different blind spots read the same
diff independently, then argue their disagreements to a verdict with evidence.
What survives is the deliverable.

The value is in the **disagreements**, not the overlap. Findings both agents
report independently are usually the obvious ones. Findings only one reports are
where the process earns its cost — half are the best findings of the run and half
are confident nonsense, and the reconciliation rounds are how you tell which.

## Non-negotiables

- **You are the judge, not a third reviewer.** You orchestrate, pair, and verify.
  Do not add your own findings to the pool — that corrupts the comparison.
- **You are also one of the debaters' harness.** Do not favor the Claude
  reviewer. When the two disagree, open the code and decide from the code.
- **No finding reaches the user unverified.** Before presenting, open the cited
  file:line for every surviving finding yourself. A reviewer's CONFIRM is a
  hypothesis, not proof.
- **A reviewer that produced no file reads produced no review.** The script
  fails those rounds; never paper over it by using the output anyway.

## Step 1 — preflight and parse the request

```bash
${CLAUDE_SKILL_DIR}/scripts/dual_review.sh preflight
```

Stop on any failure and report it — a half-configured run wastes ten minutes
before it fails.

From the user's message extract the PR reference and their task wording. Pass
their wording through verbatim as `--task`; it shapes both reviews identically.

Model and reasoning effort are per-agent and independently settable:

| Flag | Default | Accepts |
|---|---|---|
| `--claude-model` | `opus` | `opus`, `sonnet`, `fable`, or a full model id |
| `--claude-effort` | `high` | `low`, `medium`, `high`, `xhigh`, `max` |
| `--codex-model` | `gpt-5.6-sol` | any model your codex auth allows |
| `--codex-effort` | `high` | `minimal`, `low`, `medium`, `high` |
| `--timeout` | `2400` | seconds, per agent per round |

If the user names models or effort ("run codex at xhigh", "use sonnet for the
Claude side"), map it onto these flags. If they don't, use the defaults and say
which you used — don't ask.

## Step 2 — snapshot the PR

```bash
${CLAUDE_SKILL_DIR}/scripts/dual_review.sh prepare \
  --pr <url-or-number> --task "<the user's wording>" [model/effort flags]
```

Run this from a checkout of the PR's repo. It prints a `RUN_DIR` — hold onto it,
every later command takes it.

It resolves the PR's **own base branch**, fetches it, and computes the merge base
locally — never assuming the default branch. On a stacked PR those differ, and
diffing against `main` would hand the reviewers the parent branch's changes as if
they were this PR's. When the base is not the default branch, `prepare` says
`stacked=yes` and both briefs carry an explicit warning not to review the
parent's work. It also cross-checks GitHub's file list against
`merge-base..head`; a disagreement lands in `diff_scope_mismatch.txt` and means
the snapshot is misrepresenting the PR's scope — read it before going further.

Then it checks the head commit into a detached worktree, pulls the PR's existing
comments, and writes both round-1 prompts. Read the `base=… merge-base=…
stacked=…` line it prints and pass it on to the user; a stacked PR changes how
the findings should be read.

Both reviewers get **the same commit, the same diff, and the same brief**. That
is what makes the comparison mean anything.

## Step 3 — run both reviews in parallel

```bash
${CLAUDE_SKILL_DIR}/scripts/dual_review.sh run <RUN_DIR> round1 findings
```

**Launch this with `run_in_background: true`.** A real review takes 5–20 minutes
and will blow past the foreground timeout. Poll with:

```bash
${CLAUDE_SKILL_DIR}/scripts/dual_review.sh status <RUN_DIR> round1
```

Each agent lands in `<RUN_DIR>/round1/{claude,codex}.json`. If one fails, read
its `.log`, fix the cause, and re-run that round — do not proceed with one side.

While waiting, read the diff yourself. You will need the context to judge the
disagreements, and reading it now costs nothing.

## Step 4 — build the Venn diagram

Read both JSON files and pair the findings **by root cause**, not by title.
Two findings are the same finding when they would be fixed by the same edit,
even when the wording, the cited line, and the stated severity differ. One
agent's "missing await" and the other's "coroutine never scheduled" at the same
call site are one finding.

Write `<RUN_DIR>/venn.md` with three sections:

- **AGREED** — paired. Note any severity mismatch; that is still a dispute.
- **CLAUDE ONLY** (`CC-*`) — codex did not report it.
- **CODEX ONLY** (`CX-*`) — Claude Code did not report it.

Report the shape to the user now (counts per bucket, one line each). This is the
moment the run becomes interesting and it is worth surfacing before the debate.

## Step 5 — assess the PR's existing comments (optional)

`prepare` already pulled every comment on the PR into `<RUN_DIR>/comments.json`
and `comments.md`, with inline threads carrying their `RESOLVED` / `OUTDATED`
state. `comments.live.*` is the same data filtered to threads that are still
unresolved and still current — usually what you want, since a full dump on an
active PR runs to six figures of characters.

Skip this step when the PR has no comments, or when the user asked only about the
code. Otherwise it is worth doing: it tells you which existing review comments
still hold against the head commit, which are wrong, and which the PR has already
fixed — and bot reviewers in particular are confidently wrong often enough that
adjudicating them is real value.

Compose each side's prompt from `${CLAUDE_SKILL_DIR}/references/comment-brief.md`, filling
`{{SELF_FINDINGS}}` with that agent's own round-1 findings and `{{COMMENTS}}`
with the rendered comment list. Write them to
`<RUN_DIR>/comments_round/{claude,codex}.prompt.md`, then:

```bash
${CLAUDE_SKILL_DIR}/scripts/dual_review.sh run <RUN_DIR> comments_round comment-verdicts
```

This must come **after** round 1, never before. A reviewer who reads other
people's conclusions first stops reviewing and starts agreeing — the round-1
brief explicitly tells both agents not to open the comments file. It is also
independent of reconciliation, so if you want the wall-clock back you can launch
it concurrently with round 2; the script writes to separate directories.

Each comment gets `VALID` / `PARTIALLY_VALID` / `INVALID` / `ALREADY_ADDRESSED` /
`NOT_A_CLAIM`, plus `overlaps_finding` linking it to the agent's own finding when
they caught the same thing. Where the two agents disagree on a comment, resolve
it the same way you resolve any dispute — read the code yourself — or add the
`PC-*` id to the next reconciliation docket if it is worth a full argument.

Two things to carry into the final report: a **VALID comment neither agent found
independently** is a miss by both reviewers and worth flagging, and an **INVALID
comment** is worth reporting so the author can stop acting on it.

## Step 6 — reconciliation rounds

Compose each side's prompt from
`${CLAUDE_SKILL_DIR}/references/reconciliation-brief.md`, filling every `{{PLACEHOLDER}}`, and write
them to `<RUN_DIR>/roundN/{claude,codex}.prompt.md`. Then:

```bash
${CLAUDE_SKILL_DIR}/scripts/dual_review.sh run <RUN_DIR> round2 verdicts
```

Again in the background, again in parallel.

**Round 2 dockets.** Each side adjudicates what it did not raise itself:

- Claude's docket = every `CX-*` finding with no pair, plus paired findings where
  the two disagreed on severity.
- Codex's docket = every `CC-*` finding with no pair, plus the same severity
  disputes.

**Round 3+ dockets.** Only ids still in conflict. A finding's *owner* now answers
the rejection: the docket is the owner's own findings that the other side
REJECTed, and `{{PRIOR_EXCHANGE}}` carries the rejector's reasoning and evidence
verbatim so it is answering the argument, not the summary.

**An id is resolved when** the other side CONFIRMs it, or the owner withdraws it,
or both sides land on the same REVISE. It stays disputed when one CONFIRMs and
the other REJECTs.

Cap yourself at two reconciliation rounds and stop even if something is still
disputed — the loop is yours, not the script's, so nothing enforces this but you.
Convergence is not guaranteed and stalling is not free; an unresolved finding
reported honestly as unresolved is a fine outcome.

## Step 7 — verify, then present

Open the cited code for every surviving finding. Check the failure scenario is
reachable: the guard the rejector named, the caller the finder cited, the branch
that was supposedly missed. Drop anything that does not survive your own read,
and say you dropped it.

Then present:

- **Blocking** — one entry each: `file:line`, the claim, the concrete failure
  scenario, the smallest fix, and a provenance tag (`both` / `claude only,
  confirmed` / `codex only, confirmed`).
- **Non-blocking** — same shape, terser.
- **Unresolved** — anything still disputed after the last round, with both
  positions and their evidence, framed as the user's call.
- **Withdrawn** — one line per finding either agent retracted, and by whom. This
  is the run's calibration signal; it is worth showing, not hiding.
- **Existing comments** (only if Step 5 ran) — the ones still valid, the ones
  that are wrong, and the ones already fixed by a later commit in the PR. Say
  which valid ones neither reviewer found on its own.

Lead the summary with what only came out of the cross-examination — the findings
one agent missed and the confident findings that died. That is what this workflow
bought over a single review.

Offer `dual_review.sh cleanup <RUN_DIR>` to remove the worktree. Run artifacts
stay under `~/.claude/dual-review/runs/` for audit.

## Failure modes worth knowing

- **A reviewer that read nothing still answers.** Codex sandboxes every shell
  call, by default with bubblewrap, which needs an unprivileged user namespace.
  Container seccomp policies commonly deny that; codex then fails every command
  and *still returns confident, schema-valid findings* about code it never read.
  `preflight` picks the backend automatically (bubblewrap where namespaces work,
  otherwise landlock, which enforces in-kernel and needs no namespace), and `run`
  rejects any round where codex logged no successful command. If you see that
  status, treat the findings as void — do not use them because they look
  plausible.
- **Stacked PRs.** `prepare` detects them and warns both reviewers, but findings
  still arrive that belong to the parent branch. When a finding cites a line the
  diff does not touch, check it against `git diff <merge_base> <head>` before
  believing it — and say in the report that the PR is stacked, because it changes
  what "merging this" means.
- **One agent returns zero findings.** Rarely a clean PR. Check its `.log`: a
  truncated or non-JSON final message, or an effort level too low for the diff
  size — at `low` a reviewer will skim a few thousand lines and conclude nothing.
  Confirm it did enough reads before believing the verdict.
- **Both agents converge on being wrong.** Agreement is evidence, not proof —
  shared training priors produce shared blind spots. Step 6's independent read is
  not optional just because both sides agreed.
- **Huge diffs.** Past a few thousand changed lines both reviewers degrade to
  skimming. Scope the run to the subsystem that matters and say you did.

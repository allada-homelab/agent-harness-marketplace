# Dual-agent PR review — workflow

Referenced by the `dual-agent-pr-review` skill's `SKILL.md`. Nothing auto-loads this
file; the skill must be invoked explicitly (`/dual-agent-pr-review` on Claude Code).

**Contents:** Non-negotiables · Step 1 — preflight and parse the request · Step 2 — snapshot the PR · Step 3 — run both reviews in parallel · Step 4 — build the Venn diagram · Step 5 — assess the PR's existing comments (optional) · Step 6 — reconciliation rounds · Step 7 — verify, then present · Step 8 — post · When codex cannot run · Failure modes worth knowing

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
- **You run on the same harness and model family as the Claude reviewer.** Do not
  favor it. When the two disagree, open the code and decide from the code.
- **You do not settle a severity dispute alone.** When the two sides disagree on
  whether something blocks, the outcome is the reconciliation rounds' or the
  user's, never "I lean non-blocking". Every real blocker this workflow lost was
  lost that way.
- **No finding reaches the user unverified.** Before presenting, open the cited
  file:line for every surviving finding yourself. A reviewer's CONFIRM is a
  hypothesis, not proof.
- **A reviewer that produced no file reads produced no review.** The script
  fails those rounds; never paper over it by using the output anyway, and never
  hand-write or edit a `.status` file.
- **No verdict before both sides have spoken.** Do not present "the PR is clean"
  or "safe to merge" from one reviewer while the other is pending or failed. See
  *When codex cannot run*.
- **Stay independent of the code under review.** If you wrote commits on this PR
  in this session, say so up front. Do not apply fixes until reconciliation has
  finished, and apply only findings whose outcome is decided.
- **Never relabel a finding as "intended" or "a design choice"** unless the user
  said so. Carry it forward as open.

## Step 1 — preflight and parse the request

```bash
${CLAUDE_SKILL_DIR}/scripts/dual_review.sh preflight
```

Preflight checks the tools, gh and codex logins, picks codex's sandbox mode,
prints the skill version, and makes one tiny codex call — an exhausted or
logged-out codex account otherwise passes every static check and then fails
every round. Stop on any failure and report it with the fix preflight names.

From the user's message extract the PR reference and their task wording. Pass
their wording through verbatim as `--task`; it shapes both reviews identically.

Model and reasoning effort are per-agent and independently settable:

| Flag | Default | Accepts |
|---|---|---|
| `--claude-model` | `opus` | `opus`, `sonnet`, `fable`, or a full model id |
| `--claude-effort` | `high` | `low`, `medium`, `high`, `xhigh`, `max` |
| `--codex-model` | `gpt-6.1-sol` | any model your codex auth allows |
| `--codex-effort` | `high` | `low`, `medium`, `high`, `xhigh`, `max`, `ultra` |
| `--timeout` | `2400` | seconds, per agent per round |

If the user names models or effort ("run codex at xhigh", "use sonnet for the
Claude side"), map it onto these flags. If they don't, use the defaults and say
which you used — don't ask.

**Re-review.** When the user asks to re-review a PR that has an earlier run under
`~/.claude/dual-review/runs/` (same repo and PR number), this is a re-review:
pass the most recent such run dir as `--since`. Always run both reviewers on a
re-review; a solo pass of the delta is not this workflow.

## Step 2 — snapshot the PR

```bash
${CLAUDE_SKILL_DIR}/scripts/dual_review.sh prepare \
  --pr <url-or-number> --task "<the user's wording>" [model/effort flags] \
  [--since <prior RUN_DIR>] [--context-repo <path>]...
```

Run this from a checkout of the PR's repo. It prints a `RUN_DIR` — hold onto it,
every later command takes it. A `prepare` that fails before writing `config.env`
removes its partial run dir.

It resolves the PR's **own base branch**, fetches it, and computes the merge base
locally — never assuming the default branch. On a stacked PR those differ, and
diffing against `main` would hand the reviewers the parent branch's changes as if
they were this PR's. When the base is not the default branch, `prepare` says
`stacked=yes` and both briefs carry an explicit warning not to review the
parent's work. It also cross-checks GitHub's file list against
`merge-base..head`; a disagreement lands in `diff_scope_mismatch.txt` and means
the snapshot is misrepresenting the PR's scope — read it before going further.

`prepare` also writes `related_prs.md`: other PRs whose commits are in this diff,
and open PRs touching the same files. **A merged PR in the first list means
hidden stacking** — a parent that was squash-merged leaves its original commits on
this branch, `stacked=no`, and a diff that includes the parent's work. `prepare`
warns and the briefs say so; tell the user, and treat findings in that code as
out of scope. Use the second list before suggesting any follow-up PR.

`--context-repo` gives the Claude reviewer read access to a sibling checkout (for
example the service on the other side of an API this PR calls). Without one, both
briefs tell the reviewers that cross-repo claims are low-confidence, and the
reconciliation brief forbids CONFIRMing what a reviewer could not read.

With `--since`, `prepare` writes `prior.md` (the prior run's `final.md` ledger,
or its Venn when it has none) and `delta.patch` (prior head → current head), and
both briefs tell the reviewers to re-report every prior finding still present and
not to re-raise ones already rejected, rebutted, or declined unless the code under
them changed.

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

Each agent lands in `<RUN_DIR>/round1/{claude,codex}.json`. A failed codex status
line names the cause (credits, not logged in, sandbox, timeout, read no code); a
failed Claude line gives its exit code and points at `claude.log`. If one side fails, fix the cause and re-run **only that side**:

```bash
${CLAUDE_SKILL_DIR}/scripts/dual_review.sh run --only codex <RUN_DIR> round1 findings
```

`run` moves the failed attempt to `<round>/attempt-N/` first and leaves the other
side's result alone. Never rename run files, re-run a side by hand outside the
script, or write a `.status` yourself — the script's evidence gate is the only
thing standing between a review and a hallucinated one. If you cannot get a side
to run, follow *When codex cannot run*; do not proceed with one side on your own
judgment.

While waiting, read the diff yourself. You will need the context to judge the
disagreements, and reading it now costs nothing. Do not send the user a verdict
from the side that finished first.

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

On a re-review add a fourth section, **CARRIED OVER**: every finding in
`prior.md` that was not fixed, rejected, or declined, marked STILL PRESENT (a
reviewer re-reported it, or you checked it yourself) or FIXED (cite the code that
fixes it). A carried-over finding that neither reviewer re-reported and that you
cannot show fixed goes on the round-2 docket of both sides. Reviewer recall is
noisy between runs; a finding does not disappear because a reviewer stopped
mentioning it.

Report the shape to the user now (counts per bucket, one line each). This is the
moment the run becomes interesting and it is worth surfacing before the debate.

## Step 5 — assess the PR's existing comments (optional)

`prepare` already pulled every comment on the PR into `<RUN_DIR>/comments.json`
and `comments.md`, with inline threads carrying their `RESOLVED` / `OUTDATED`
state. `comments.live.*` is the same data filtered to threads that are still
unresolved and still current — usually what you want, since a full dump on an
active PR runs to six figures of characters. **On a re-review use the full
`comments.*`**: the resolved threads are where the author answered the last round.

Skip this step only when the PR has no comments, or when the user asked only
about the code — and say which. Otherwise it is worth doing: it tells you which
existing review comments still hold against the head commit, which are wrong, and
which the PR has already fixed — and bot reviewers in particular are confidently
wrong often enough that adjudicating them is real value. It is also what Step 8
uses to link an overlapping thread from the new inline comment.

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
they caught the same thing. Where the two agents disagree on a comment, say so
in the report — never merge two different verdicts into one — and resolve it the
same way you resolve any dispute: read the code yourself, or add the `PC-*` id
to the next reconciliation docket if it is worth a full argument.

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

Again in the background, again in parallel. A side whose docket is empty gets no
prompt file; `run` records it as skipped rather than failing. Write the heredoc
that builds a prompt with a quoted delimiter (`<<'EOF'`) — an unquoted one lets the
shell expand the backticks in the findings.

**Round 2 dockets are mandatory.** Each side adjudicates what it did not raise:

- Claude's docket = every `CX-*` finding with no pair, plus paired findings where
  the two disagreed on severity, plus carried-over findings no one re-reported.
- Codex's docket = every `CC-*` finding with no pair, plus the same severity
  disputes and carry-overs.

Do not skip round 2 because "there is nothing to dispute": a one-sided finding
nobody else has adjudicated is unverified, not agreed. If a side cannot run,
present its docket as **unadjudicated** (see *When codex cannot run*).

**Round 3 dockets.** Only ids still open. A finding's *owner* now answers:

- every finding of its own the other side REJECTed — the owner gets a rebuttal
  before anything is dropped;
- every finding of its own the other side REVISEd to a different severity, when
  the owner has not yet accepted that severity.

`{{PRIOR_EXCHANGE}}` carries the other side's reasoning and evidence verbatim so
the owner is answering the argument, not the summary.

**An id is resolved when** the other side CONFIRMs it, or the owner withdraws it,
or both sides land on the same REVISE (same severity). It stays **disputed** when
one CONFIRMs and the other REJECTs, when the two REVISE to different severities,
when a REVISE was never answered by the owner, or when the round that would have
settled it was voided. A disputed id goes to **Unresolved** in Step 7 with both
positions — never to Non-blocking because you leaned that way.

Cap yourself at two reconciliation rounds (round 2 and round 3) and stop even if
something is still disputed — the loop is yours, not the script's, so nothing
enforces this but you. Convergence is not guaranteed and stalling is not free; an
unresolved finding reported honestly as unresolved is a fine outcome.

## Step 7 — verify, then present

Open the cited code for every surviving finding. Check the failure scenario is
reachable: the guard the rejector named, the caller the finder cited, the branch
that was supposedly missed. **Then apply common sense to every non-blocking
finding: if this merges, will a user or a caller hit something that does not
work** — in this PR's feature, in a shared component it touched, or anywhere else?
If yes, it is blocking, whatever the reviewers labelled it; where the two
reviewers both called it non-blocking and you disagree, list it as Unresolved with
your reasoning. A behavior that does not match its own docs or contract is a
behavior bug first, not a documentation nit — judge it by what a user sees. **Verify the mechanism, not just that the line
exists** — when a claim rests on a tool default, a flag, a dependency group, or a
config value, run the command or read the file that settles it, and cite it. Say
"inferred" for anything you could not check. Drop anything that does not survive
your own read, and say you dropped it.

Write `<RUN_DIR>/final.md` — the ledger a later re-review reads. One line per id:
id · `file:line` · severity · action · disposition (blocking / non-blocking /
unresolved / withdrawn / rejected / dropped-by-judge) · provenance. Step 8 appends
what was posted.

Then present, in this order and with these headings:

- **Blocking** — one entry each: `file:line`, the claim, the concrete failure
  scenario, **one** recommended fix (code when it is short; alternatives as a
  sub-bullet, never a menu in place of an answer), and a provenance tag (`both` /
  `claude only, confirmed` / `codex only, confirmed`).
- **Non-blocking** — the same shape, terser, each tagged with its `category`
  (e.g. `documentation`) so the reader can tell what kind of issue it is; say
  "fine as a follow-up" on a `fix-later` one, and list `nit` ones last. A severity
  label and a recommendation must agree: if you would hold the PR for it, it is
  blocking.
- **Unresolved** — everything still disputed after the last round, including
  every severity split, with both positions and their evidence, and your read
  labelled as yours — framed as the user's call.
- **Withdrawn** — findings their *owner* retracted, and by whom.
- **Rejected** — findings the other side REJECTed and the owner did not defend,
  or that you dropped after your own read — say which. Withdrawn and Rejected are
  the run's calibration signal; show them, do not merge them.
- **Existing comments** (only if Step 5 ran) — the ones still valid, the ones
  that are wrong, and the ones already fixed by a later commit in the PR. Say
  which valid ones neither reviewer found on its own, and where the two
  reviewers' verdicts on a comment differed.
- **Judge observations** — anything you noticed that neither reviewer raised,
  labelled as yours, outside the counts.

Lead the summary with what only came out of the cross-examination — the findings
one agent missed and the confident findings that died. That is what this workflow
bought over a single review. Put the full PR URL in the summary and in every
later message about it. Then go to Step 8.

## Step 8 — post

**A draft review is the default.** On anyone else's PR, once Step 7 has verified
the findings, post them without asking as a **pending** GitHub review — the review,
its inline comments and the disclosure, visible only to the user until they submit
it from the PR's Files tab. Two requests change that: `submit` ("post it directly",
"submit it") publishes the review at once, and `no-post` ("don't post", "just show
me") shows the draft here and stops. Never decide on the user's behalf to post less
than every verified finding.

**The user's own PR** (the PR author is the user): there is no one to post to.
Offer the findings as a fix list instead, blocking first; if they say fix,
apply only decided findings, commit and push them, then re-run this workflow with
`--since` before calling the PR done — `prepare` reviews the PR's pushed head, and
fixes made by the judge introduce defects of their own.

**Anyone else's PR** — draft one review:

- **Every issue is its own inline comment** — Blocking, Non-blocking and
  Unresolved alike. Posting never silently drops a verified finding, never folds
  one into the review body, and never substitutes a thread reply for it.
  Non-blocking ones are labelled so the author can triage them, not withheld.
  Prefix each comment body with its label — severity, then the finding's
  `category`: `**[Blocking · correctness]**`, `**[Non-blocking · documentation]**`,
  `**[Nit · convention]**` (`Nit` for an action of `nit`). Never put the action
  in the label — "Non-blocking · fix-before-merge" reads as a contradiction; when
  a non-blocking fix can wait, say so in the comment text.
- **Unresolved findings are inline questions**, labelled `**[Open question]**`,
  stating both positions in one or two sentences.
- **Anchor every comment inside a changed hunk.** Use the finding's `file` and
  `posting_line`, and check each one before posting:
  `dual_review.sh anchors <RUN_DIR> <path> <line>` exits 0 only for a line GitHub
  will accept. GitHub rejects the **whole** review when one comment's anchor is
  outside the diff. When the check fails or `posting_line` is 0, the finding is
  still inline: on the nearest changed line in `file` if it has one; otherwise, with
  `submit` only, as a file-level comment on `file` when the PR touches it (posted
  separately, see below — a pending review cannot hold one); otherwise on the
  changed line that leads to the defect. Whenever an
  inline comment sits on a line other than the defect's, say the real
  `file:line` in its body.
- **Link, don't merge, an existing thread.** When a still-live thread already
  makes the same claim (Step 5's `overlaps_finding`, or a VALID `PC-*`), the
  finding still gets its own inline comment; say "also raised in <thread URL>" in
  it so the author can resolve both together.
- **The review body is a short index** — counts and one line per item, each
  pointing at its inline comment. No findings live only in the body. No model
  names, round counts, "findings that died", or judge observations; those are for
  the user, not the author.
- **Event: `REQUEST_CHANGES`** whenever the review has any comment, non-blocking
  ones included — it holds the merge until the user's own once-over (see the
  disclosure below). A draft carries no event: GitHub creates a review with the
  `event` left out as PENDING, and the user picks the event when submitting, so
  tell them to submit it as **Request changes**. Never `APPROVE` from this workflow
  unless the user says so in words.
- **Disclose the automation.** In a draft, end the review body with the
  disclosure, so it goes public only with the review. With `submit`, post it as
  one top-level PR comment after the review instead. Either way it says the review
  came from this workflow and that the user will do a human pass once every
  comment is addressed. Take the login from `gh api user --jq .login`, never
  hard-code one:

  > These review comments were drafted automatically by
  > [@\<login\>](https://github.com/\<login\>)'s `/dual-agent-pr-review` — two
  > independent AI reviewers whose findings were cross-checked against each other
  > and the code. Once each comment has been addressed, I'll do a once-over myself.

Only with `no-post`: show the user the draft here and stop; post later only what they
then pick. If their answer does not map to exactly one of post all / pick ids /
don't post, ask again rather than guessing — "post the fix" is not "post only that
one".

Before posting, re-check the PR:

```bash
gh pr view <url> --json state,headRefOid,mergedAt
```

- **Merged or closed** → stop and tell the user; do not post to it.
- **Nothing verified survived** → post nothing, not even the disclosure.
- **Head moved since `prepare`** → diff old head to new head for the files the
  findings cite; drop or re-anchor findings the new commits fixed or moved, and
  say which.
- **The user already posted a review on this PR since `prepare`** → show it and
  ask before posting a second one.
- **The user already has a pending review on this PR** (`gh api
  repos/<owner>/<repo>/pulls/<n>/reviews --jq '.[] | select(.state == "PENDING")'`
  — only the user's own pending review is visible to them) → show it and ask;
  never delete or submit it yourself.

Post the whole review in one call — a JSON body with the short index (and, in a
draft, the disclosure), a `comments` array of `{path, line, side: "RIGHT", body}`,
and `"event": "REQUEST_CHANGES"` only with `submit` (leave `event` out for a draft)
— to `gh api repos/<owner>/<repo>/pulls/<n>/reviews --method POST --input <file>`.
Check that the response's `state` is `PENDING` for a draft, `CHANGES_REQUESTED`
with `submit`. With `submit` only, follow it with one call per file-level comment
(`gh api …/pulls/<n>/comments --method POST -f body=… -f path=<file> -f
commit_id=<head oid> -f subject_type=file`) and then the disclosure with `gh pr
comment <url> --body-file <file>`. Then append to `final.md` what was posted — the
review URL and id, whether it is pending or submitted, each comment URL (with
`submit`), the disclosure comment URL (with `submit`), and every verified finding
that was **not** posted with the reason — and show the user that ledger with the
full review URL. For a draft, tell them how to publish it: open the PR's Files
tab and choose **Finish your review → Request changes**, or ask you to submit it,
which is `gh api repos/<owner>/<repo>/pulls/<n>/reviews/<id>/events --method POST
-f event=REQUEST_CHANGES`.

Offer `dual_review.sh cleanup <RUN_DIR>` to remove the worktree. Run artifacts
stay under `~/.claude/dual-review/runs/` for audit and for the next `--since`.

## When codex cannot run

The default is always to finish the dual review. Recommending "just run Claude"
is never the first option — the user has rejected it every time it was offered.

1. Read the cause from `status` (credits, not logged in, sandbox, timeout). Give
   the user the one-line fix — refill the workspace, `codex login`, re-run
   preflight — and stop until it is done. Then `run --only codex` the round.
2. Never work around a denied launch: no hand-built `codex exec`, no patched copy
   of the script, no `--sandbox danger-full-access` you chose yourself. If a
   permission check denies the script, tell the user which command to allow.
   Inside a container the script already picks `danger-full-access` itself.
3. Only if the user explicitly chooses to go on without codex: label the result
   **SINGLE-REVIEWER** at the top. Codex's docket becomes **unadjudicated** — you
   do not adjudicate it yourself, and you may not lower a severity codex gave in
   an earlier round. A review the user pastes from elsewhere is an external
   opinion: keep it in `<round>/external.md`, never in `codex.json`.

## Failure modes worth knowing

- **A reviewer that read nothing still answers.** Codex sandboxes every shell
  call; on Linux that is bubblewrap, which needs an unprivileged user namespace
  (codex dropped its landlock fallback by 0.160 — `use_legacy_landlock` now
  panics). Container seccomp policies deny that; codex then fails every command
  and *still returns confident, schema-valid findings* about code it never read.
  `preflight` runs a command through codex's own read-only sandbox. Where that
  cannot start **inside a container**, codex runs with `--sandbox
  danger-full-access` and preflight says so: the dev containers get no seccomp
  change, so the container is the only boundary — the PR's checkout can reach
  that container's credentials and network. On a host, preflight fails instead.
  `run` additionally voids any round where codex ran no successful command in the
  worktree (reading only the run dir does not count), and flags a verdict round
  with fewer than one worktree command per three items as **low evidence** —
  spot-check those citations before relying on them.
- **The account, not the sandbox.** In a container codex is logged in per
  container, and a workspace can run out of credits mid-run; both make codex
  answer nothing or fail fast. Preflight's login check and one-line probe catch
  them up front; mid-run, `status` names them.
- **Stacked PRs.** `prepare` detects them and warns both reviewers, but findings
  still arrive that belong to the parent branch. When a finding cites a line the
  diff does not touch, check it against `git diff <merge_base> <head>` before
  believing it — and say in the report that the PR is stacked, because it changes
  what "merging this" means. Hidden stacking (a squash-merged parent) shows up
  only in `related_prs.md`.
- **One agent returns zero findings.** Rarely a clean PR. Check its `.log`: a
  truncated or non-JSON final message, or an effort level too low for the diff
  size — at `low` a reviewer will skim a few thousand lines and conclude nothing.
  Confirm it did enough reads before believing the verdict.
- **Both agents converge on being wrong.** Agreement is evidence, not proof —
  shared training priors produce shared blind spots. Step 7's independent read is
  not optional just because both sides agreed.
- **`prepare` cannot fetch.** It prints git's own error; `bad object
  refs/prefetch/…` means stale `git maintenance` prefetch refs, and the message
  names the command that deletes them.
- **Huge diffs.** Past a few thousand changed lines both reviewers degrade to
  skimming. Scope the run to the subsystem that matters and say you did.

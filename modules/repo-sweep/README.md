# repo-sweep

A whole-repository review that can be run again. It finds issues, proves each
one, keeps them in a ledger, and on request opens the pull requests that fix
them. It runs on Claude Code, pi and dsh, and it is built so that a local model
can drive it: a command holds the state and writes every child agent's
instructions, so the orchestrating model only runs commands in order.

Two skills, one for each mode:

| Skill | Mode | What it does |
|---|---|---|
| `repo-sweep` | read-only | splits the repo into parts, fans out finders and validators, reports |
| `repo-sweep-fix` | read and write | one branch, worktree and pull request per part with confirmed findings |

`repo-sweep-fix` is user-invoked only (`disable-model-invocation`), and it
merges only with `--merge`.

## What a `repo-sweep` run does

1. `repo-sweep plan` updates the ledger from the last run (a merged pull
   request makes its findings `fixed`; a finding whose quoted code is gone
   becomes `recheck`), then splits the tracked text files into parts of at most
   `--chars` characters, keeping a directory together when it fits.
2. A `repo-sweep:finder` agent reads each part and makes five passes:
   simplify, cleanliness, bugs, edge cases, performance. It records findings
   with `repo-sweep record`. Each finding carries a line of code quoted from
   the file, and **the command rejects a finding whose quote is not in the
   file**. The finder is told what the ledger already holds for its files, so a
   second run reports only what is new.
3. A `repo-sweep:validator` agent then takes the candidates of each part and
   gives each a verdict: `confirmed`, `rejected` or `unproven`. **A `confirmed`
   verdict needs proof the command can accept**: an exact quote of the code
   that shows the issue, or a command with its output.
4. The orchestrator checks the proof of every high-severity confirmed finding
   and reports.

Up to `--concurrency` agents (default 4) run at once. Finders and validators
have no edit or write tool.

## The ledger

One sqlite database per repository, outside the checkout, under
`$XDG_STATE_HOME/repo-sweep/` (default: `$HOME/.local/state/repo-sweep/`;
`REPO_SWEEP_HOME` overrides it). Clones and worktrees of the same
origin share it. `repo-sweep status` prints its path.

| Status | Meaning |
|---|---|
| `candidate` | a finder reported it; not yet validated |
| `confirmed` | validated with proof; `repo-sweep-fix` will pick it up |
| `rejected` | a validator showed the claim is wrong; kept so it is not reported again |
| `unproven` | a validator could not show it either way |
| `recheck` | it was open, and its quoted code is no longer in the file; the next sweep that covers the file decides `fixed` or `confirmed` |
| `pr-open` | a fix pull request is open for it |
| `fixed` | its pull request merged, a validator found the issue gone, or its file was removed |
| `needs-human` | a fixer skipped it, or the reviewer reverted its fix; the note says why |
| `wontfix` | closed by the user: `repo-sweep set <id> wontfix --note "<why>"` |

## Commands

```
repo-sweep plan [path ...] [--chars N]   update the ledger, split the repo, queue the finders
repo-sweep sync                          start a run without a sweep: clear the queue, update the ledger
repo-sweep next [-n N] [--fix]           claim queued units and write their brief files
repo-sweep record <unit>                 a child's report, as JSON on stdin; checked before it is stored
repo-sweep release <unit>                requeue a unit whose child returned without finishing it
repo-sweep pr <unit> <url>               record the pull request of a finished fix unit
repo-sweep set <id> <status> [--note T]  change one finding by hand
repo-sweep status                        ledger path, open units, counts
repo-sweep report [--out DIR]            every finding as Markdown; --out writes one file per part
```

Stdlib Python only. `plan` and `sync` call `gh pr view` when the ledger has
`pr-open` findings.

## Install

- Claude Code: `/plugin marketplace add allada-homelab/agent-harness-marketplace`
  then `/plugin install repo-sweep@agent-harness-marketplace`
- pi: install the marketplace package; the skills are globbed in by the root
  manifest.
- dsh: add the bundle; the harness's skills and agents bridges discover the
  skills and the three agents.

Children run on Opus on Claude Code and on `large-default` on any other
harness. The agent files carry no `model` key.

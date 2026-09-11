---
name: pr-flow
description: Use whenever a task will change files in a git repository. Work happens on a new branch in a worktree, is pushed as a PR, and the PR is watched until green; also for "watch this PR", "is CI green", "merge when green", "clean up merged worktrees".
user-invocable: true
harness: [claude, pi, dsh]
tags: [git, workflow]
---

# pr-flow

The main checkout of every repo stays on its default branch. Work that changes
files happens on a branch in a worktree, goes up as a PR, and the PR is watched
until green. The tool is `pr-flow` — on a fleet host it is on `PATH`; otherwise
run `./pr-flow.py` beside this file with `python3`. Every verb prints a final
line `pr-flow: <verb> <verdict> [<url-or-path>]` on success; a refusal exits 2
with a `pr-flow: <reason>` line on stderr instead. Act on the verdict.

## Procedure

1. **Read first, on main.** Investigation, planning and questions need no branch.
   The trigger for step 2 is the first edit, not the task start.
2. **Start** — `pr-flow start <slug>` from the main checkout (`<slug>` becomes
   `feat/<slug>`; give a full `fix/…` name to choose the prefix; `--base
   <branch>` builds off something other than the default branch, and is
   remembered for `open`/`watch`/`teardown` on this branch). It prints the
   worktree path — use that printed path, never a guessed one — under
   `.claude/worktrees/` (named after the branch, `/` replaced by `-`), and
   creates the `.agents/worktrees` symlink in any repo on first use. From here
   every file operation and command uses that path — absolute paths for file
   tools, `cd <path> &&` or `git -C <path>` for commands.
   A dirty main checkout (uncommitted edits, possibly someone else's) makes
   `start` refuse by default — rerun with `--carry` to move all of it into the
   new worktree, or `--carry <path>...` for specific paths only.
3. **Work and commit** in the worktree. Stage only files you changed.
4. **Open** — `pr-flow open`. Pushes, creates the PR against the branch's
   recorded base (or reuses the branch's), prints the full URL. Repeat the URL
   in every message that mentions the PR. It refuses when the branch's PR is
   already merged (exit 2 — run `pr-flow start` for new work instead) and opens
   a fresh PR when the old one was closed.
5. **Watch** — `pr-flow watch`, after every push. It blocks up to one hour; it
   prints `next poll in Ns` to stderr before each wait, and tolerates transient
   `gh` failures (gives up after 10 in a row, exit 2). An empty check list is
   polled for up to `--no-checks-grace` seconds (default 300) before being
   treated as green, so a check that lands late still counts. It returns one
   verdict:
   - `green` (exit 0): report the URL; the turn is done unless merge was authorized.
   - `merged` (exit 0): someone merged it; the tool already tore the worktree down.
   - `checks-failed` (10): the failed job's log is in the output. Fix it in the
     worktree, commit, push, watch again.
   - `conflict` (11): in the worktree `git fetch origin && git merge origin/<base>`,
     resolve, commit, push, watch again. Never force-push to resolve a conflict.
   - `review` (12): unresolved review threads, changes requested, a draft PR, or
     one blocked by branch protection. Address each thread (bot reviewers
     included) or the blocking condition, push, reply on the thread, watch again.
   - `closed` (13): stop and report.
   - `timeout` (14): nothing finished within the hour; watch again.
   - `attempts-exhausted` (15): five fix rounds used. Stop and report what is
     still red — the user decides.
   `--merge` binds to the exact commit it last saw green
   (`--match-head-commit`); if the head moved since, it refuses (exit 2) rather
   than merging a commit nobody watched — run watch again.
6. **Merge only when told.** `pr-flow watch --merge` is allowed only when the
   user said, ahead of time and for this task, that the PR may be merged when
   green. Silence means no. A green PR without that permission ends the turn
   with the URL.
7. **Teardown** — `pr-flow teardown` after the PR is merged (`--merge` does it
   itself). `pr-flow gc` tears down every worktree whose PR has merged; run it
   when you notice stale worktrees.

## Editing on main anyway

Allowed only when the user says so for that task, or the file never goes
through a PR (an untracked `.env`, a local overlay). A hint may appear after
an edit on main — it is a reminder to run `pr-flow start`, not a block.

## Traps

- A linked worktree has no `.env` and is not the checkout services run from:
  never render or restart a service from a worktree; deploy from main after
  merge.
- Slugs, not UUIDs, in branch and directory names — a UUID-shaped path trips
  secret scanners.
- A tool that switches the main checkout to another branch to "test" a change
  breaks everything that watches main; test the worktree in place instead.

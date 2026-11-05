---
name: pr-flow
description: Use whenever a task will change files in a git repository, or needs a worktree — creating one, setting it up, working in one or removing it. Work happens on a new branch in a worktree, is pushed as a PR, and the PR is watched until green; also for "make a worktree", "watch this PR", "is CI green", "merge when green", "clean up merged worktrees".
user-invocable: true
harness: [claude, pi, dsh]
tags: [git, workflow]
---

# pr-flow

The main checkout of every repo stays on its default branch. Work that changes
files happens on a branch in a worktree, goes up as a PR, and the PR is watched
until green. The tool is `pr-flow` — on Claude Code the plugin puts it on
`PATH`; otherwise run `./pr-flow.py` beside this file with `python3`. Every verb prints a final
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
   tools, `pr-flow -C <path> <verb>` and `git -C <path>` for commands. Run each
   `pr-flow` command bare, exactly as `pr-flow -C <path> watch --merge`: no
   `cd <path> &&` in front, no pipe such as `| tail` after, no `export` or
   inline `VAR=value`. A wrapped command can miss the permission rule that
   allows `pr-flow` and be held for review, and a pipe reports the pipe's exit
   code instead of the verdict's. There is nothing to trim: `watch` prints one
   stderr line per poll and the verdict line.
   A dirty main checkout (uncommitted edits, possibly someone else's) makes
   `start` refuse by default — rerun with `--carry` to move all of it into the
   new worktree, `--carry <path>...` for specific paths only, or `--leave-dirty`
   when none of it is yours: it stays on main, untouched. A local branch
   of the same name with no worktree is refused up front, and if creating the
   worktree fails after a carry the carried work is put back on main first.
3. **Work and commit** in the worktree. Stage only files you changed.
4. **Open** — `pr-flow open`. Pushes, creates the PR against the branch's
   recorded base (or reuses the branch's), prints the full URL. In a clone of
   a fork the PR targets the upstream repo with an owner-qualified head, as
   gh requires. Repeat the URL
   in every message that mentions the PR. It refuses (before pushing) a branch
   with no commits ahead of its base — usually a commit a hook rejected. It
   refuses when the branch's PR is already merged (exit 2 — run `pr-flow start`
   for new work instead) and opens a fresh PR when the old one was closed.
5. **Watch** — `pr-flow watch`, after every push. It blocks up to an hour,
   polling (`next poll in Ns` and, right after a push, `PR head … is not the
   pushed … yet` on stderr are normal) and waiting out CI that starts late. It
   returns one verdict:
   - `green` (exit 0): report the URL; the turn is done unless merge was authorized.
   - `merged` (exit 0): someone merged it; the tool already tore the worktree down.
   - `checks-failed` (10): the failed job's log is in the output. Fix it in the
     worktree, commit, push, watch again.
   - `conflict` (11): sync with the base the way the output says, resolve,
     commit, push, watch again. That is `git fetch origin && git merge
     origin/<base>` and a plain push, unless the repo merges by rebase (no merge
     commits allowed): a rebase merge cannot replay a merge commit, so there it
     is `git rebase origin/<base>` and `git push --force-with-lease`, run only
     with the user's OK. Never force-push in any other case.
   - `review` (12): unresolved review threads, changes requested, a draft PR, or
     one blocked by branch protection. Address each thread (bot reviewers
     included) or the blocking condition, push, reply on the thread, watch again.
     When the output says CI is green and only the `ownership` check is waiting,
     there is nothing to fix: the PR needs an owner's approval. Report that.
   - `closed` (13): stop and report.
   - `timeout` (14): nothing finished within the hour; watch again.
   - `attempts-exhausted` (15): five fix rounds used and the sixth verdict is
     still a fix-class one. Stop and report what is still red — the user
     decides.
   `--merge` merges only the exact commit it saw green; if the head moved, it
   refuses (exit 2) — watch again. A `green` with a behind-the-base hint means
   sync as for `conflict` before a merge will go through. A `green` reached only
   because a wait timed out (no check ever reported) exits 0 but `--merge`
   refuses and says so: merge by hand once you have evidence CI ran. A refused
   merge prints gh's message and the likely cause.
6. **Merge only when told.** `pr-flow watch --merge` is allowed only when the
   user said, ahead of time and for this task, that the PR may be merged when
   green. Silence means no. A green PR without that permission ends the turn
   with the URL. A standing approval for a class of PR in the user's own
   instructions (e.g. "wiki-only PRs may merge when green") counts — use
   `pr-flow watch --merge-if-only <prefix>` (e.g. `.wiki/`): it merges only when
   every path the PR changes, at the commit it saw green, is under that prefix,
   and otherwise reports `green` unmerged with the first path outside it. Repeat
   the flag for a class spanning several paths; a prefix also matches an exact
   file (`--merge-if-only agents/modules.tsv --merge-if-only dsh/profiles/`).
7. **Teardown** — `pr-flow teardown` after the PR is merged (`--merge` does it
   itself). It removes the worktree, deletes the local branch **and deletes the
   branch on origin**; a branch counts as merged when it is an ancestor of
   `origin/<base>` or GitHub has a merged PR for it (squash and rebase merges
   leave no ancestor). When a `devc` executable is on PATH it first runs
   `devc down <worktree>` to remove the worktree's dev container, image and
   per-worktree volumes; a failure there is a warning, never a blocked teardown.
   `pr-flow gc` tears down every worktree whose PR has
   merged; run it when you notice stale worktrees.

## Editing on main anyway

Allowed only when the user says so for that task, or the file never goes
through a PR (an untracked `.env`, a local overlay). A hint may appear after
an edit on main — it is a reminder to run `pr-flow start`, not a block.

A git command that changes the main checkout while it is on a protected
branch (`commit`, `checkout`, `switch`, `reset`, `restore`, `merge`, `rebase`,
`stash` and the like; `fetch`, `pull --ff-only`, `stash list|show|create` are fine)
**is** blocked. Do it in a worktree. A repo whose convention is to commit on
that branch directly is opted out by the user, never by you:
`git config pr-flow.allowMainCheckout true`.

## Worktree setup

- Make worktrees only with `pr-flow start`. A bare `git worktree add` is
  blocked; a repo's own worktree task or a harness's built-in worktree command
  skips the rules below too.
- Never copy, clone or symlink a tool-built environment into a worktree — a
  virtualenv (or a `.direnv/` holding one), `.tox`/`.nox`, a CMake build dir:
  they hold absolute paths into the main checkout, so the worktree silently
  runs main's code. `start` refuses a `.worktreeinclude` entry holding a
  virtualenv. Let the worktree build its own — uv does on the first `uv run`.
- Seed only gitignored files the worktree needs to run (`.env`, local config)
  through `.worktreeinclude`; everything tracked is already there.
- A repo with its own setup step (a bootstrap script, `direnv allow`) needs it
  run in the new worktree before tests or commits, never the main checkout's
  tooling pointed at the worktree.
- Worktrees share the machine with main: ports, local databases, containers.
  Starting a service from a worktree takes them from whoever holds them.
- Worktrees also share one git stash stack. `pop`, `drop`, `clear` and a bare
  `apply` can take another session's entry and are blocked; set work aside
  with a WIP commit, or `git stash create` and `git stash apply <sha>`.
- Name a worktree by its literal absolute path (`pr-flow -C <path>`,
  `git -C <path>`), never through a shell variable: harnesses reset the shell's
  directory between calls, and guards cannot expand `$VAR` to see the target.
- Remove a worktree with `pr-flow teardown`, which refuses unmerged work —
  never `rm -rf` or `git worktree remove --force`. `git worktree prune`
  without `-n` deletes the metadata of worktrees this side cannot see, such as
  a dev container's.

## Traps

- A linked worktree has no `.env` and is not the checkout services run from:
  never render or restart a service from a worktree; deploy from main after
  merge.
- Slugs, not UUIDs, in branch and directory names — a UUID-shaped path trips
  secret scanners.
- A tool that switches the main checkout to another branch to "test" a change
  breaks everything that watches main; test the worktree in place instead.

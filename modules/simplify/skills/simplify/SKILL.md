---
name: simplify
description: Review changed code for reuse, simplification, efficiency and altitude (code at the wrong layer) cleanups, then apply the fixes. Scope is the given pull request, branch, files or diff ref; with no argument, the uncommitted diff, or the current branch against the default branch when the tree is clean. Quality only, not a bug hunt. Use before pushing a diff longer than a screen, or when asked to simplify, clean up or tidy a change. A pull request target needs the gh CLI.
user-invocable: true
argument-hint: "[PR number or URL, branch, files, or a diff ref]"
harness: [pi, dsh]
tags: [refactor, quality, review]
---

# Simplify

**This invocation is the task. Start on step 1 now — do not ask what to do.**

Review a change for code that could be reused, simpler, cheaper or at a better
layer, then apply the fixes — never changing what the code does, never
committing. Target: $ARGUMENTS — when none is given, the uncommitted changes,
or the current branch's changes against the default branch if the tree is
clean.

## Agents

One agent ships beside this skill, type `simplify:reviewer`, dispatched once
per lens: `reuse`, `simplification`, `efficiency`, `altitude`.

- **pi and dsh**: the `delegate_agent` tool with `agent_type` set to the type
  above. On pi the tool is inactive until this skill is invoked; if it is
  missing, run `/agents` once.
- **No delegation tool at all**: run each lens yourself, sequentially, using
  the agent's body as your brief. The definition is in
  `./../../agents/reviewer.md` beside this skill.

Every child sees none of this conversation: give it the checkout path, the
exact diff command, the changed files, the guideline file paths, its lens, and
any focus or constraint the user stated. Issue the four calls together in one
message so they run in parallel.

## Steps

1. **Resolve the target** and state it in one line. Find the default branch
   with `git symbolic-ref --short refs/remotes/origin/HEAD` (fall back to
   `gh repo view --json defaultBranchRef`), and `git fetch` what you diff
   against.
   - A number or a pull request URL is a **pull request**: `gh pr view <pr>
     --json number,headRefName,baseRefName,isCrossRepository`. Its base is
     `origin/<baseRefName>`.
   - An existing path is a **file**: the scope is that file's uncommitted
     changes (`git diff HEAD -- <path>`), or the whole file when it has none.
   - A name `git show-ref` finds under `refs/heads/` or
     `refs/remotes/origin/` is a **branch**, diffed against
     `origin/<default>`.
   - Anything else `git rev-parse --verify` accepts (a commit, `HEAD~3`, a
     range) is a **diff ref**, reviewed in place with `git diff <ref>`. It
     must be reachable from `HEAD` (`git merge-base --is-ancestor`); if not,
     stop and ask for its branch instead.
   - Remaining text that is none of these is a **focus**: pass it to every
     reviewer.

2. **Pick where to edit**, and run every later command against that path —
   `git -C <path>`, absolute paths for file tools.
   - Files, a diff ref, no argument, or a branch or pull request whose head is
     the current branch: **here**, in place.
   - A branch already checked out in another worktree (`git worktree list
     --porcelain`): **that worktree** — git will not check one branch out
     twice. Say so in the report; it may hold someone's uncommitted work, so
     edit only the lines the findings name.
   - Otherwise a new worktree at `.agents/worktrees/simplify-<branch>` (`/` in
     the branch name becomes `-`). If `git check-ignore -q .agents/worktrees`
     fails, first add `/.agents/worktrees/` to
     `$(git rev-parse --git-common-dir)/info/exclude` so the main checkout
     stays clean. Then, for a branch, `git worktree add <path> <branch>`; for
     a pull request, `git worktree add --detach <path>` and run `gh pr
     checkout <number>` inside it, which also handles a fork's head.

3. **Collect the diff.** Write down the exact command that prints it — `git
   -C <path> diff <merge-base>` for a branch or pull request (`git merge-base
   origin/<base> HEAD`), `git diff HEAD` for the working tree, `git diff
   <ref>` for a diff ref — and the changed files it lists. Find the guideline
   files: the root `CLAUDE.md` and `AGENTS.md`, and any in the directories the
   change touches. If the diff is empty, say so and stop.

4. **Review.** Dispatch `simplify:reviewer` four times in one message, one
   lens each, with everything the Agents section lists.

5. **Apply.** Reviewers over-report. Handle each finding in turn:
   1. Open `file` and check that the `old` block is in it, character for
      character. If not, skip it as "stale".
   2. Check the `evidence` yourself: open the cited helper, re-run the grep,
      read the loop. If it does not hold, skip it with the reason.
   3. Skip it if it changes behavior or conflicts with a guideline file.
   4. Otherwise replace `old` with `new` using the edit tool.
   When two findings touch the same lines, apply the first and skip the other.

   Never `git checkout`, `git restore`, `git stash` or `git reset` a file —
   the scope is usually uncommitted work, and those discard it. To back out an
   edit, reverse it with the edit tool. Never commit or push.

6. **Check.** If the project has a fast check — a lint, a type check, the
   tests next to the edited files — run it in the edit location and read its
   exit code. When it fails because of an edit you made, reverse that edit and
   list the finding as skipped. Do not run a long full suite.

7. **Report**, briefly:
   - the target and where the edits landed (a worktree path, with `git
     worktree remove <path>` for when the user is done with it);
   - one line per applied fix: `file:line` — what was cut or changed;
   - each skipped finding and why;
   - the check you ran and its result, or that none exists;
   - anything the reviewers flagged as out of scope (bugs included) in one
     line each, untouched.

   Say plainly if nothing needed changing.

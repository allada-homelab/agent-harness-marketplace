# simplify

Review a change for cleanups and apply them, on pi and dsh. Ships the
`simplify` skill (`/skill:simplify` on pi, `/simplify` on dsh) and the one
subagent it dispatches four times — `simplify:reviewer` — through
`delegate_agent`. The skill is model-invocable too, so an agent can run it on
its own diff before pushing.

What a run does:

1. resolves the target — a pull request, a branch, files or a diff ref given
   as the argument, else the uncommitted changes, else the branch's diff
   against the default branch;
2. picks where to edit: in place for the current branch, the existing
   worktree when the branch is checked out elsewhere, or a new worktree under
   `.agents/worktrees/` for any other branch or pull request;
3. dispatches four reviewers in parallel, one lens each — **reuse** (an
   existing helper already does this), **simplification** (same behavior in
   less, clearer code), **efficiency** (work the change does not need) and
   **altitude** (code at the wrong layer); each returns at most 5 findings as
   exact `old`/`new` edits with checkable evidence — for reuse, the existing
   helper's full body, which is what exposes a look-alike that differs;
4. checks each `old` block and its evidence against the code and applies the
   ones that hold without changing behavior, then runs the project's fast
   check if it has one;
5. reports each fix, each skipped finding with its reason, and the worktree
   path if one was made. Nothing is committed; you review the diff.

Quality only: bugs a reviewer notices are listed as out of scope, not fixed.

## Install

- pi: install the marketplace package; the skill is globbed in by the root
  manifest.
- dsh: add the bundle; the harness's skills and agents bridges discover the
  skill and the agent.

Not for Claude Code, which ships its own `/simplify`: this module has no
`.claude-plugin/plugin.json` and no marketplace entry, and the skill is
scoped `harness: [pi, dsh]`.

## Provenance

Modeled on Claude Code's built-in `/simplify` (reuse, quality and efficiency
review, then fix), with a fourth lens, altitude, and pull request and branch
targets that are edited in a worktree. It replaces the `code-simplifier`
module: that module's clarity rules and balance rules — a port of the
`code-simplifier` plugin from `anthropics/claude-plugins-official`
(Apache-2.0) — carry over into the `simplification` lens, and its rule never
to `git checkout`, `restore`, `stash` or `reset` the user's work carries over
into the skill.

---
name: code-review
description: Review a GitHub pull request and post one comment with only the high-confidence issues. Five parallel reviewers (guideline compliance, shallow bug scan, git history, prior pull-request comments, in-code comment guidance) raise candidates, a scorer rates each 0-100 and anything under 80 is dropped, and a second eligibility check runs before the comment is posted. Use when asked to code-review, review or audit a pull request, or when a pull request needs a review comment; not for reviewing an uncommitted local diff. Needs the gh CLI.
user-invocable: true
argument-hint: "[pr-number-or-url]"
tags: [review, github]
---

# Code review

Provide a code review for the pull request. Review target: $ARGUMENTS — when
none is given, the pull request of the current branch (`gh pr view`).

Everything here is read-only: use `gh` (`gh pr view`, `gh pr diff`, `gh pr
list`, `gh search`, `gh issue`, `gh api`) and the local checkout to read, and
`gh pr comment` once at the end to write. Never edit files, never run a build,
typecheck or test suite — CI runs those separately and they are not part of
this review — and never use web fetching where `gh` will do.

## Agents

Three agents ship beside this skill; name them by type and dispatch them with
whatever this harness has:

| Type | Model tier | Job |
|---|---|---|
| `code-review:triage` | small | eligibility check · guideline-file discovery · change summary |
| `code-review:reviewer` | mid | one review lens per dispatch |
| `code-review:scorer` | small | one confidence score per candidate issue |

- **Claude Code**: the Agent tool with `subagent_type` set to the type above.
- **pi and dsh**: the `delegate_agent` tool with `agent_type` set to the type
  above. On pi the tool is inactive until this skill is invoked; if it is
  missing, run `/agents` once.
- **No delegation tool at all**: do each step yourself, sequentially, using the
  agent's body as your brief. The definitions are in `./../../agents/` beside
  this skill.

Every child sees none of this conversation: give it the pull request reference,
its duty or lens, and every input the step names. Issue independent calls
together in one message so they run in parallel.

## Steps

Outline these steps as a task list first, then follow them precisely.

1. **Eligibility.** Dispatch `code-review:triage` with duty *eligibility*. Stop
   if it answers `SKIP` — the pull request is closed, a draft, needs no review
   (automated, or trivially and obviously fine), or already has a `### Code
   review` comment from an earlier run.
2. **Guideline files.** Dispatch `code-review:triage` with duty *guideline
   files*. It returns paths only: the root `CLAUDE.md` / `AGENTS.md` and any
   in the directories the pull request touches.
3. **Summary.** Dispatch `code-review:triage` with duty *summary*. Steps 2 and
   3 do not depend on each other; run them together.
4. **Five reviewers in parallel.** Dispatch `code-review:reviewer` five times,
   one lens each — `guidelines`, `bugs`, `history`, `prior-prs`, `comments` —
   giving every one the pull request reference, the summary from step 3 and
   the guideline paths from step 2. Collect every candidate issue with the
   reason it was flagged.
5. **Score every candidate in parallel.** For each issue dispatch
   `code-review:scorer` with the pull request reference, the issue exactly as
   the reviewer returned it, and the guideline paths. The scorer carries the
   0-100 rubric; do not paraphrase it. Keep the `SCORE` and `WHY` lines.
6. **Filter.** Drop every issue scoring below 80. If none remain, stop: post
   nothing.
7. **Re-check eligibility.** Repeat step 1. The pull request may have been
   closed, merged or reviewed while the reviewers ran; if it now says `SKIP`,
   stop.
8. **Post** with `gh pr comment <pr> --body-file <file>` (write the body to a
   temporary file so Markdown survives the shell). Keep it brief, avoid
   emojis, cite and link every issue.

## Comment format

Follow this shape exactly. With three issues:

```markdown
### Code review

Found 3 issues:

1. <brief description> (CLAUDE.md says "<...>")

<permalink>

2. <brief description> (some/dir/AGENTS.md says "<...>")

<permalink>

3. <brief description> (bug due to <file and code snippet>)

<permalink>

<sub>Automated review. React with a thumbs-up if it was useful, a thumbs-down if not.</sub>
```

With no surviving issues you never reach this step (step 6 stops). Never post
a "no issues found" comment: silence is the signal.

## Permalinks

Each issue links to the code on GitHub with the **full 40-character commit
SHA** of the pull request head (`gh pr view --json headRefOid`), because the
comment is rendered as Markdown and nothing in it is evaluated:

```
https://github.com/<owner>/<repo>/blob/<full-sha>/<path>#L<start>-L<end>
```

- The repository must be the one under review.
- `#` after the path, then `L<start>-L<end>`.
- Include at least one line of context on each side, centred on the lines the
  issue is about (an issue on lines 5-6 links `L4-L7`).
- Never write a shell substitution in place of the SHA; it will not expand.
- A guideline citation links the guideline file the same way.

---
name: code-review
description: Review a GitHub pull request with parallel reviewers and a confidence scorer, and post one comment holding only the high-confidence issues. Use when asked to code-review, review or audit a pull request, or when a pull request needs a review comment; not for reviewing an uncommitted local diff. Needs the gh CLI.
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

| Type | Job |
|---|---|
| `code-review:triage` | eligibility check · size · guideline-file discovery · change summary |
| `code-review:reviewer` | one review lens per dispatch, or (small tier) all five lenses combined with inline scoring |
| `code-review:scorer` | one batch of confidence scores — every candidate issue of this review, in a single dispatch |

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
2. **Size, guideline files, summary.** Dispatch `code-review:triage` three
   times — duty *size*, duty *guideline files*, duty *summary* — together;
   none of the three depends on the others. Size returns `FILES`, `LINES` and
   `GENERATED_ONLY`; guideline files returns paths only (the root
   `CLAUDE.md` / `AGENTS.md` and any in the directories the pull request
   touches); summary returns a short description of the change.
3. **Pick a tier.** **small** when `LINES` from step 2 is under 50, or
   `GENERATED_ONLY` is `yes`; **normal** otherwise. Below 50 changed lines
   there is rarely more than one class of issue for five independent lenses
   to disagree about, and a docs- or lockfile-only diff has no logic for them
   to review at all — five reviewers plus a scorer added tool calls with
   nothing to find. Every other change gets the full fan-out.
4. **Reviewer(s).**
   - **small**: dispatch `code-review:reviewer` once with lens `all`, giving
     it the pull request reference, the summary from step 2 and the guideline
     paths from step 2. It reviews through every lens itself and scores each
     issue it keeps inline (`SCORE` and `WHY`) — skip step 5 for this tier.
   - **normal**: dispatch `code-review:reviewer` five times, one lens each —
     `guidelines`, `bugs`, `history`, `prior-prs`, `comments` — giving every
     one the pull request reference, the summary and the guideline paths.
   Collect every candidate issue with the reason it was flagged.
5. **Score (normal tier only).** Dispatch `code-review:scorer` **once**, for
   the whole review, with the pull request reference, the full numbered list
   of candidate issues exactly as the reviewers returned them, and the
   guideline paths. The scorer carries the 0-100 rubric; do not paraphrase
   it. Keep the `SCORE` and `WHY` lines for every issue. Only dispatch a
   second scorer, in parallel, if the candidate list is large enough that one
   dispatch would blow past its own tool budget — never one scorer per
   candidate.
6. **Filter.** Drop every issue scoring below 80. This threshold gates one
   thing only: whether the issue is posted in this skill's comment. It says
   nothing about whether a fix is mandatory — a caller reading the comment
   (a lead, a merge gate) may treat every posted issue, or some higher band,
   as required to fix before merge; that decision is the caller's, not this
   skill's. If none remain, stop: post nothing.
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

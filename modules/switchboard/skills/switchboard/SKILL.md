---
name: switchboard
description: Coordinates concurrent Claude Code sessions on this machine through the `switchboard` CLI — an overview of every session and what it is working on, each session's history of worktrees, branches, PRs and tickets, status posts and messages, a shared todo board, a ledger of shared-state changes, and leases on shared local resources such as a dev stack. Use before starting, stopping or migrating a shared local resource that has a switchboard lease, when work may overlap another session's branch or worktree, when handing work to or asking something of another session, and when asked what sessions are running, what a session is doing, or which session worked on a ticket, PR, branch or file.
harness: [claude]
tags: [coordination, sessions]
---

# switchboard

Several sessions share this machine, its shared local resources and the user's attention.
`switchboard` (on PATH) is how sessions see each other instead of making the user carry messages.
A resource such as a local dev stack gets a lease when an adapter in `$SWITCHBOARD_HOME/adapters/`
defines it; `switchboard who` lists the leases. One rule is enforced: a Bash command that an
adapter says starts, stops, resets or migrates its resource is denied until this session holds
that lease. The rest are yours to keep. Another skill may add rules for a specific resource.

## Rules

1. **A shared resource is a lease.** Before you start, stop, take over, reset or migrate it:
   `switchboard stack status` (it also reports what is *actually* running and flags a mismatch).
   Then `stack join --est <min> --purpose "<what you will prove>"`, run `stack wait` with
   `run_in_background`, and keep doing other work until it returns. Release as soon as you are done:
   `stack release --result "pass: … | fail: … ; left running: …"`. Join only when you can use it the
   moment it is yours; setup work (worktree bootstrap, a plain image build) happens before you
   join. When it is free and nobody is queued, `stack acquire --purpose "…"` takes it at once.
   `stack` is short for `lease <resource>` when exactly one adapter is installed.
2. **Never stop or take over what someone else runs.** If `status` shows it running under
   another session or with no lease, ask that session (rule 5) or the user. Take it over only
   once you hold the lease and they agree.
3. **Say what you are doing, and keep it current.** `switchboard doing "<ticket/branch: one line>"`
   as soon as you know the task, and again whenever you switch ticket, branch or PR; an outdated
   status misleads more than none. `switchboard post "<update>"` at milestones others would care
   about (a shared branch pushed, the main branch broken, a PR merged, a finding another session
   needs). Your worktree, branch, tickets, prompts and opened PRs are recorded for you, and an
   opened PR is posted; the prompt hook reminds you when your status is unset or older than your
   work.
4. **Record shared-state changes with their undo.** Any write to a shared DB or volume (a
   migration stamp, a seeded row, a flag flipped in local data):
   `switchboard ledger add "<what>" --resource <db> --rollback "<exact undo>"`. A write an adapter
   recognizes is logged as a bare `write` and nudges you for this entry; `stack release` warns
   about writes you never described and about observed facts (such as a migration revision) that
   changed during your lease. Restore them before releasing, or say in `--result` why they stay.
5. **Talk to sessions instead of making the user relay.** Before asking the user about another
   session's work, ask that session.
   - `switchboard post "<question or heads-up>" --to <name>`: it reaches a busy session after its
     current tool call (or before it goes idle) and stays on record. The output says when it will
     land; an idle session gets it at its next prompt, so also wake it with the built-in
     `SendMessage` tool, addressed by the `msg:` name `who` prints.
   - Need the answer to continue? Add `--wait 10m` (run it in the background), or carry on and
     the reply arrives as a post.
   - A post addressed to you shows `→ you #<id>`: act on it, then answer with
     `switchboard reply <id> "<answer>"`. Never leave one unanswered.
   - `post` without `--to` broadcasts to every session, including later ones.
6. **Use the board for work that outlives this conversation**: `todo add … --project <p>`,
   `todo take <id>` before starting someone's item, `todo done <id> --note "<PR url>"`.

New posts addressed to you or to everyone arrive in your context automatically; you don't poll.

## Overview: answering "what is running" from any session

Any session can oversee the others; there is no special one.

- **What is running, and what is each session on?** `switchboard who`: active sessions with
  their branch, status (or last ask), PR and ticket, then each lease and what is actually
  running. `--all` adds sessions quiet for over 6h.
- **What is session X doing / what did it do?** `switchboard show X` (a name, session id or id
  prefix; ended sessions too): status, last ask, history of worktrees, branches, PRs and tickets,
  its posts, ledger entries, todos, and its transcript path. `--prompts` adds the user's prompts.
  For detail beyond that, search the transcript with bounded greps; never read it whole.
- **Which session worked on Y?** `switchboard find Y`: a ticket (`AI-3217`), PR URL or number,
  branch, worktree path, file name or word, matched against what sessions touched, asked,
  posted and ledgered, newest first.

## Commands

All commands, flags, the adapter contract and the state layout:
[references/commands.md](references/commands.md).

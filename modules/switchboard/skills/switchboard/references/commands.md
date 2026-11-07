# switchboard commands

Every command acts as the current session (`CLAUDE_CODE_SESSION_ID`). Run from a plain terminal,
it acts as `<user>-terminal`, which can hold leases and post like any session.

| Command | Does |
|---|---|
| `who [--all]` | The overview. Each active session: name (and the `SendMessage` name when it differs), latest worktree@branch, last seen, busy/idle, held lease, its status or else its last prompt, its latest PR and ticket. Then each lease and what is observed running, and the open board count. Sessions quiet for over 6h are folded away unless `--all`. |
| `show <session> [-n N] [--prompts]` | One session, live or ended, by name, id or id prefix: status, last prompt, cwd, transcript path, history (worktrees, branches, PRs, tickets; `--prompts` adds prompts), last posts and ledger entries, open todos. |
| `find <term> [-n N]` | Sessions that touched `<term>` (ticket, PR, branch, worktree, file, word) in their history, prompts, status, posts, ledger entries or todos, newest first, with up to 3 matches each. |
| `whoami` | Your name, session id, pid. |
| `doing "<text>" [--announce]` | Set your one-line status; `--announce` also posts it. Empty text clears it. `stack acquire --purpose` sets it when unset. |
| `name <new>` | Rename yourself in switchboard (not in `SendMessage`). |
| `post "<text>" [--to <session>] [--topic <t>] [--wait <dur>]` | Post to the feed; `--to` delivers to one live session only (name or id prefix) and says when it will land and the `SendMessage` name that wakes it. `--wait` blocks until that session replies, printing the reply; exit 3 at the timeout. |
| `reply <id> "<text>"` | Answer post `#<id>`; it goes to that post's author only, marked `(re #<id>)`. |
| `feed [-n N] [--all] [--id N]` | Recent posts to everyone and to you (`--all`: every post); `--id` prints one post in full (delivered posts are cut at 300 characters and name it). |
| `todo add "<title>" [--project P] [--link URL] [--note N] [--take \| --owner <session>]` | Add a board item; `--take` owns it and marks it `doing`; `--owner` assigns it to another session. |
| `todo ls [--mine] [--project P] [--all]` | Open items (`todo`, `doing`, `blocked`); `--all` adds `done` and `dropped`. |
| `todo take <id> [--force]` | Own an item. Refuses one another live owner has open, unless `--force`. |
| `todo set <id> [--status S] [--title T] [--link URL] [--note N] [--release]` | Edit an item; `--release` clears its owner. |
| `todo done <id> [--note N]`, `todo drop <id> [--note N]` | Close an item; posts it. |
| `ledger add "<what>" [--resource R] [--rollback "<undo>"]` | Record a change to shared state; with `--resource` it is also posted. |
| `ledger ls [-n N] [--resource R] [-v]` | Recent entries; `-v` shows the full observed snapshot. |
| `stack <verb>` | `lease <resource> <verb>` for the one installed adapter's resource. |
| `lease <resource> status` | Holder, queue with estimated start times, what the adapter observes running, mismatches, last ledger entries. |
| `lease <resource> join --est <dur> --purpose "<p>"` | Queue (FIFO). Re-joining updates your estimate and purpose. |
| `lease <resource> leave` | Leave the queue. |
| `lease <resource> wait [--timeout <dur>]` | Block until you hold it (polls every 15 s); exit 3 at the timeout (default 240m). Run it in the background. |
| `lease <resource> acquire [--purpose P] [--ttl <dur>]` | Take it now if it is free and you are first in the queue (or the queue is empty). Exit 1 otherwise, with the reason. |
| `lease <resource> renew [--ttl <dur>]` | Extend your lease (default 60m). |
| `lease <resource> release --result "<r>"` | Give it up; records the result and an observed snapshot, posts it, and tells the next in queue. `--note` and `--summary` are aliases. |
| `lease <resource> kick --note "<why>"` | Remove someone else's lease and tell them directly. Ask them or the user first; it does not stop their processes. `--reason` is an alias. |
| `digest` | What a new session is shown at start. |

A duration `<dur>` is minutes (`90`) or `90m`, `2h`, `1h30m`; `--ttl`, `--minutes` and `--est` are
aliases on `join`, `acquire` and `renew`. Any resource name works with `lease`; only an adapter's
resource is enforced and probed.

## Lease semantics

- A lease lasts `max(est, 60)` minutes unless `--ttl` says otherwise. Each tool call by the holder
  renews it, so it lapses 60 minutes after the holder goes quiet.
- It ends early when its holder's Claude Code process exits (the pid is gone) or `/clear` replaces
  the holder session in the same process. An expired or ended holder's lease is free to the first
  in the queue, and the takeover is recorded.
- Releasing or losing a lease never stops anything. The observed snapshot in the ledger says what
  was left running. `release` prints what is still running, and warns (and posts, as
  `UNACCOUNTED`) when an observed fact whose name contains `alembic` changed since your `acquire`,
  or when your shared-DB writes have no `ledger add` describing them.
- While the resource runs with no lease, `status` and the session banner name the last holder and
  its release note. Acquiring it then records that you adopted it and tells that session.
- Lease and ledger posts reach only sessions working where an adapter applies; `feed` still shows
  them everywhere.
- The gate is off inside a dev container, which has its own empty state.

## Adapters

An adapter is a Python file in `$SWITCHBOARD_HOME/adapters/` (default `~/.switchboard/adapters/`)
that defines one leased resource. Every `*.py` there is loaded; `SWITCHBOARD_ADAPTERS=a,b` loads
only those stems, and `none` loads none. With no adapter, everything but enforcement and probing
still works.

| Name | Required | Contract |
|---|---|---|
| `RESOURCE` | yes | The lease name, e.g. `"dev-stack"`. |
| `applies(cwd) -> bool` | yes | Whether a session in `cwd` works where the resource lives. Gating, warnings and lease posts apply only there. |
| `classify(command) -> str \| None` | yes | For a Bash command, a verb phrase such as `"starts or stops"` when it changes the resource (the deny reads "that command starts or stops the shared dev-stack"), else `None`. Called before every Bash call, so keep it to pattern matching. |
| `probe() -> dict` | yes | A read-only look at what is running: `running` (bool or `None` for unknown), `summary` (one line), `served_from` (checkout paths the running copy serves), `facts` (name → value, recorded at acquire and release). An exception is reported as `probe failed`, never raised. |
| `shared_writes(command) -> list[str]` | no | Shared-state resources a Bash command wrote to; each becomes a `write` ledger entry. |
| `warn(command, cwd) -> str \| None` | no | An advisory shown before a command runs; never blocks. |

## State

One SQLite file, `$SWITCHBOARD_HOME/switchboard.db` (default `~/.switchboard/`). It is safe to
delete: sessions re-register on their next prompt (their history is lost). Host only: sessions
inside a dev container don't see it.

## What the hooks record

- **Session start:** cwd, git worktree and branch, transcript path. A different session that ran
  in the same process (before `/clear`) is ended and its leases released.
- **Each prompt:** the prompt (first 300 characters), ticket ids (`AI-3217`) and PR URLs in it,
  the worktree and branch of the cwd. After a session's first 10 minutes, a reminder (at most
  hourly) when its `doing` is unset or older than its latest branch, PR or ticket.
- **Each tool call:** an Edit or Write into another git worktree notes that worktree and
  branch; `git checkout|switch|worktree add`, `pr-flow start` and `gh pr checkout` re-read the
  branch (from `pr-flow start ok <path>` when given); `gh pr create` and `pr-flow open` note the
  PR URL from the output and post `opened <url>`.
- **Turn end (Stop):** when a direct post to the session arrived during the turn, the turn
  continues with the unread posts so it can act or reply before going idle; broadcasts alone
  wait for the next prompt.

A worktree or branch is recorded when it changes, a PR or ticket the first time a session
touches it.

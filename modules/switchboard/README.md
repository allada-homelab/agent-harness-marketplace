# switchboard

Coordination for concurrent agent sessions (Claude Code, pi, dsh) on one machine: a registry of who is doing what,
threaded messages between sessions, a todo board, a ledger of shared-state changes, and leases on
shared local resources such as a dev stack. It informs, and blocks one thing: a Bash command that
changes a leased resource from a session that doesn't hold the lease. On pi and dsh the hooks run
through the maintainer's dotfiles hook runners.

| Part | What it is |
|---|---|
| `bin/switchboard` | The CLI (Python 3 standard library only), on the Bash tool's PATH while the plugin is enabled. |
| `hooks/hooks.json` | SessionStart registers the session, ends one `/clear` replaced, and injects a short digest; PreToolUse denies a resource-changing Bash command without the lease; UserPromptSubmit and PostToolUse record the session's history (worktree, branch, PRs, tickets, prompts, shared-DB writes) and deliver new posts, and PostToolUse renews the holder's lease; Stop delivers direct posts that arrived during the turn before the session goes idle. |
| `skills/switchboard/` | When and how agents use it; commands and the adapter contract in `references/commands.md`. |
| `test/` | End-to-end tests that drive the CLI and hooks against a temporary state dir and a stand-in adapter. |

Resources come from adapters, Python files in `$SWITCHBOARD_HOME/adapters/` (default
`~/.switchboard/adapters/`). The module ships none: another plugin or the user installs the ones
for their machine. The contract is in `skills/switchboard/references/commands.md`.

## Why it exists

Agent transcripts from machines running several sessions at once showed the same failures:

- **The user was the lock and the message bus.** Sessions started a shared stack on top of one
  that another session was using, and the user relayed "I'm using the stack" and "done with it"
  between sessions by hand.
- **Nothing recorded what was really running**, or which checkout it served.
- **Shared DB state had no owner.** Migration stamps left by one branch were rediscovered
  independently by several sessions.
- **Sessions couldn't see each other's branches, worktrees or progress**, and a question for
  another session went through the user.

Claude Code's built-in `SendMessage` wakes an idle session; switchboard adds what that lacks: a
registry with status lines and each session's history (so any session can answer "who is on
what" and "who touched X"), a persistent feed with threaded direct posts (`post --to`, `reply`,
`post --wait`), the board, the ledger and leases. A direct post reaches a busy session at its next
tool call or, through the Stop hook, before it goes idle; an idle one at its next prompt, unless
the sender wakes it with `SendMessage`. pi and dsh have no wake: a direct post waits for that
session's next prompt or tool call (or its Stop hook).

## Design notes

- **Identity.** Each session is keyed by the id its harness exports to shell commands:
  `CLAUDE_CODE_SESSION_ID`, `PI_SESSION_ID` or `DSH_SESSION_ID`, in that order. Hooks read
  `session_id` from their stdin, which is the same id; the pi and dsh hook runners also export
  their variable to handlers, which is how a hook tells which harness it serves. On Claude the
  SessionStart hook also exports `SWITCHBOARD_SESSION_ID` through `CLAUDE_ENV_FILE` as a fallback.
  A hook payload with `agent_id` (a subagent) never creates a session row.
- **Liveness.** Liveness is the harness pid (Claude: `CLAUDE_PID`, else the nearest `claude`
  ancestor; pi: `PI_PID`, set by its hook runner), not a heartbeat, so a crashed holder's lease frees itself without a TTL wait. There
  is no SessionEnd hook (the repo's hook contract has none): an exited process is detected by its
  pid, and `/clear` (pi: `/new`, `/resume`, `/fork`), which keeps the process, by SessionStart seeing a
  new session id in it. A dsh session has no pid of its own (one server hosts many sessions), so it
  counts as live for 12h after it was last seen, like a terminal, and never replaces another.
- **Display names.** These come from Claude Code's own registry, `~/.claude/sessions/<pid>.json`,
  so `who` shows the name `SendMessage` takes. That file is internal and undocumented: it is read
  only for display, and every field is optional.
- **State.** SQLite in WAL mode with a busy timeout, and `BEGIN IMMEDIATE` around lease decisions.
  This is safe for many processes on one host. It is not meant for a bind mount into containers.
- **Costs.** Every hook spawns one `python3`. The PreToolUse (Bash only) and PostToolUse hooks do
  no probing: they touch SQLite and call the adapters' pattern matchers. Two git calls run on a
  prompt, on an edit into a different worktree than the last one, and after a branch-moving
  command.
- **Why the lease is enforced.** An advisory note after the command arrives too late: the
  resource is already restarted under its holder. A hook only sees the agent's Bash tool, so the
  user's own terminal is never blocked.

## Checks

```bash
python3 -m pytest modules/switchboard/test
bin/check.sh
```

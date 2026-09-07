# Install on pi

pi installs a git repository as one package, so the whole marketplace arrives at
once and the root `package.json` `pi` manifest decides what loads: every
`modules/*/skills/*` directory except the modules scoped to Claude. This repo
ships no pi extensions — `/name` commands and hook delivery come from the pi
harness-side foundation (`hook-runner.ts`, `skill-commands.ts`) that lives in
the maintainer's dotfiles harness layer (private) and is always installed there.

```
pi install git:github.com/allada-homelab/agent-harness-marketplace@v0.1.0
```

User scope is always trusted, so a global install never hits the project-trust
prompt. Narrow what loads with the object form of `settings.packages`:

```json
{ "packages": [ { "source": "git:github.com/allada-homelab/agent-harness-marketplace@v0.1.0",
                  "skills": ["!modules/get-shit-done/**"] } ] }
```

Two things to know:

- `pi install` rewrites `~/.pi/agent/settings.json`. If something else renders
  that file (dotfiles), declare the package there instead.
- Skills and their descriptions ride on every API request of the agentic loop.
  Exclude what you do not use.

With the harness-side foundation installed, its `skill-commands` extension
makes each user-invocable skill available as `/name` beside pi's native
`/skill:name`, and its `hook-runner` extension runs every installed module's
`hooks/hooks.json`; `Stop` hooks are observe-only on pi (a block becomes a
follow-up message), see `hook-contract/README.md`.

## Verified 2026-09-06 (pi 0.84.1, throwaway `$HOME`, local-path install)

Captured before the 2026-09-07 move: `skill-commands-pi` and `hook-runner-pi`
were sibling modules of this repo at the time, installed alongside it. On the
current layout, `/research` and the `SessionStart` delivery below come from
the pi harness-side foundation described above, not from this repo.

```
$ pi install /path/to/agent-harness-marketplace
Installed /path/to/agent-harness-marketplace
$ pi list
User packages:
  /path/to/agent-harness-marketplace
```

A probe extension dumped `pi.getCommands()` at `before_agent_start`, with a
temporary sibling module carrying a SessionStart hook:

```
PROBE ["extension research","skill skill:research","skill skill:pragmatic-code-review","skill skill:get-shit-done"]
echo.json: {"session_id": "pi-…", "cwd": "…/work", "hook_event_name": "SessionStart", "source": "startup"}
```

`/research` registered by skill-commands-pi, the three portable skills loaded,
the Claude-only modules stayed excluded, and hook-runner-pi delivered the
SessionStart event to the hook script.

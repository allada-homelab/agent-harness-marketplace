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
                  "skills": ["!modules/agent-transcripts/**"] } ] }
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

## Verified 2026-09-16 (pi 0.84.1, throwaway `$HOME`, local-path install)

This is `tests/smoke/pi.sh`, which installs the checkout into a throwaway
`$HOME` and dumps `pi.getCommands()` from a probe extension at
`before_agent_start`. `/name` commands and hook delivery are harness-side
foundation and are not exercised from this repo.

```
$ pi install /path/to/agent-harness-marketplace
Installed /path/to/agent-harness-marketplace
$ pi list
User packages:
  /path/to/agent-harness-marketplace
```

```
PROBE ["extension llama","skill skill:pr-flow","skill skill:plan-for-dummies",
       "skill skill:feature-dev","skill skill:code-review","skill skill:browser",
       "skill skill:transcript-sweep","skill skill:transcript-review",
       "skill skill:transcript-query","skill skill:transcript-ingest",
       "skill skill:transcript-export-pi","skill skill:transcript-export-dsh",
       "skill skill:transcript-export-claude"]
  ok   pi exited from the probe (rc 0)
  ok   portable skills loaded
  ok   Claude-only modules excluded
```

Every portable skill loaded as `skill:<name>`, and `dual-agent-pr-review` — the
only module the root `pi` manifest excludes — stayed out.

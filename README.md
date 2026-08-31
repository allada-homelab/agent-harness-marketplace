# agent-harness-marketplace

The **harness-neutral tree**: skills, commands and hooks that more than one coding
agent can read from one place. Cloned (or symlinked) to **`~/.agents`** on every host.

Consumers: **Claude Code**, **pi** (`@earendil-works/pi-coding-agent`) and **dsh**
(`@deepseek-ai/dsh`). Per-harness *config* — settings, doctrine, rules, output styles —
deliberately does **not** live here; it stays in
[`.davidallada-developer-setup`](https://github.com/davidallada/.davidallada-developer-setup),
which is also what installs the links below.

## Layout

```
~/.agents/
├── skills/<name>/SKILL.md   # Agent Skills spec — all three harnesses
├── commands/<name>.md       # slash commands (Claude) / prompts (pi)
├── lib/<name>/…             # support assets for a command or skill (NOT auto-discovered)
└── hooks/<name>.py          # Claude hook contract; pi + dsh runners pending
```

`lib/` exists because every `*.md` under `commands/` is discovered as a command — a
workflow file or prompt template placed there would register as one. Anything a command
loads at runtime goes in `lib/<command-name>/` and is referenced as
`~/.agents/lib/<name>/…`, a path that resolves the same for all three harnesses.

## How each harness finds this

| Harness | Global | Project (`<repo>/`) | Mechanism |
|---|---|---|---|
| dsh | `$DSH_AGENTS_HOME ?? ~/.agents/skills` | `<repo>/.agents/skills` | **native** — no config |
| Claude Code | `~/.claude/skills`, `~/.claude/commands` | `<repo>/.claude/skills` | symlink |
| pi | `~/.agents/skills` **natively**; `~/.pi/agent/prompts` | ancestor `<dir>/.agents/skills` to the git root | native for skills, symlink for commands |

Verified against pi 0.84.1 (`dist/core/skills.js:330-334`, `dist/config.js:445`): it reads
`<agentDir>/skills` and `<agentDir>/prompts`, **follows symlinks** for both skill dirs and
`SKILL.md` files, ignores frontmatter keys it does not know, and its prompt placeholders are
a superset of Claude's (`$ARGUMENTS`, `$1`, `$@`, plus `${1:-default}` and `${@:2:3}` slices
— `dist/core/prompt-templates.js:58`).

**pi reads this tree natively too** — `dist/core/package-manager.js:1968` for
`$HOME/.agents/skills` and `:280` for every ancestor `<dir>/.agents/skills` up to the git
root, with the user directory always trusted (`dist/core/trust-manager.js:151`). The path is
hardcoded to the real home; `PI_CODING_AGENT_DIR` does not move it. So two of the three
harnesses find this tree with no configuration at all, and Claude is the only one needing
symlinks.

**Know the cost model before adding a skill.** A visible skill's name and description sit in
pi's system prompt on *every request of the agentic loop*, not once per user message —
captured at the wire on 2026-08-31: one `pi -p` prompt produced **9 API requests, all 9
carrying the block**. Skills are cheap to add and not free to keep. Which skills a given
client sees is a filtering question, answered by tags (below) rather than by moving files.

## Scope: location, not a flag

Where a thing lives settles **scope**. `~/.agents/` is portable content; `<repo>/.agents/`
is content *about that repo* — e.g. the setup repo's own `.agents/skills/` holds
`harbor-evals` and `shift-enter-audit`, which only mean anything inside it.

What location does *not* settle is **harness applicability**, so frontmatter carries that
and only that:

```yaml
harness: [claude]      # omitted ⇒ portable to every harness
```

Today the marker is documentation — nothing filters on it. It is here because the
constraint is real (`claude-transcript-*` read `~/.claude/projects`), and because the
generators that will read it (a Claude plugin manifest, the pi/dsh hook runners) need it
declared before they can.

## Hooks

`hooks/` is a declared slot, not yet populated. Claude's hook contract — an external
script, event JSON on stdin, exit code to block, stdout JSON to replace — maps onto pi's
`tool_call`/`tool_result` extension events and dsh's `tools/pre-execute` /
`tools/post-execute` pipeline, so one script can serve all three behind a ~150-line runner
per harness. Those runners belong in `agent-plugins`; until they exist, the Claude hooks
stay in the setup repo where their `settings.json` paths already point.

**The one gap:** turn refusal. Claude's `Stop` hook can exit 2 and force a turn to
continue; dsh's `agent/turn-stopping` returns `void` and pi's `turn_end` is observe-only.
Turn-level hooks therefore degrade to annotations off Claude. Every **tool-level** hook
ports at full strength.

## Adding something

1. Pick the scope: portable → here; about one repo → that repo's `.agents/`.
2. Add `harness:` only if it genuinely cannot run everywhere.
3. Runtime assets → `lib/<name>/`, referenced as `~/.agents/lib/<name>/…`.
4. Nothing to regenerate — dsh reads this tree directly and the other two are symlinked.

Design record: `docs/superpowers/plans/2026-08-31-fleet-consolidation-analysis.md` in the
setup repo.

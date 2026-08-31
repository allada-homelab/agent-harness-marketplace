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
├── policy/secrets.json      # credential policy every harness enforces
├── index.yaml               # generated catalog — who each thing is for
└── hooks/<name>.py          # Claude hook contract; pi + dsh runners pending
```

`policy/` holds enforcement *data*, not code: the credential patterns and
deny-read paths that `claude/hooks/redact-secret-output.py`, pi's
`secret-guard.ts` and the dsh guard plugin all compile at runtime. They were
transcribed by hand into each language before, which is exactly how they drifted
— one copy knew `sk-example` was a placeholder and another did not. Regexes are
written in the Python∩JavaScript intersection (numbered groups, no verbose mode,
`[\s\S]` instead of a dotall flag) so both engines take them unmodified, and
every consumer fails **open and loud** if the file is missing: a redactor that
wedges the tool loop is worse than the leak it prevents.

`lib/` exists because every `*.md` under `commands/` is discovered as a command — a
workflow file or prompt template placed there would register as one. Anything a command
loads at runtime goes in `lib/<command-name>/` and is referenced as
`~/.agents/lib/<name>/…`, a path that resolves the same for all three harnesses.

## How each harness finds this

| Harness | Global | Project (`<repo>/`) | Mechanism |
|---|---|---|---|
| dsh | `$DSH_AGENTS_HOME ?? ~/.agents/skills` | `<repo>/.agents/skills` | **native** — no config |
| Claude Code | `~/.claude/skills`, `~/.claude/commands` | `<repo>/.claude/skills` | symlink |
| pi | `~/.agents/skills` **natively**; `~/.pi/agent/prompts` | ancestor `<dir>/.agents/skills` — **only in a trusted repo** | native for skills, symlink for commands |

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

**One asymmetry to know about project scope.** dsh reads `<repo>/.agents/skills`
unconditionally; pi puts it behind its project-trust gate (`~/.pi/agent/trust.json`),
while treating the user-level `~/.agents/skills` as always trusted. So a headless
`pi -p` in an untrusted repo sees global skills and silently no project ones — it
cannot prompt for trust. Verified against both real agents on 2026-08-31.

## Scope, applicability, context

Three orthogonal questions, three different answers.

**Scope is location.** `~/.agents/` is portable content; `<repo>/.agents/` is content
*about that repo* — e.g. the setup repo's own `.agents/skills/` holds `harbor-evals` and
`shift-enter-audit`, which only mean anything inside it.

**Applicability and context are frontmatter**, on the skill or command itself:

```yaml
harness: [claude]        # who can use it. Omitted ⇒ every harness.
tags: [homelab]          # what it is about. A client may exclude by tag.
```

Both apply to **commands** as well as skills: `dual-agent-pr-review` drives the
`claude` and `codex` CLIs, so it is `harness: [claude]` and pi's prompts view is
empty rather than offering pi a workflow it cannot carry out.

`index.yaml` collects both into one catalog so a client can select a subset without
opening every file. It is **generated** — never hand-edit it:

```sh
uv run --script bin/agents-index.py --write     # regenerate after adding a skill
uv run --script bin/agents-index.py --check     # fail if stale
uv run --script bin/agents-index.py --select --harness pi --exclude-tag homelab
```

Selection is then materialized differently per harness, because they differ in what they
can be told — that part lives in the consuming repo
(`scripts/render-agent-views.py` in `.davidallada-developer-setup`):

| Harness | How the selection is applied |
|---|---|
| claude | `~/.claude/skills` and `~/.claude/commands` point at rendered **views** — directories of symlinks. Claude has no exclude mechanism, so the directory is the filter. |
| dsh | `agentsHome` on its `skill-filesystem` row points at a rendered view root, same reason. Config rather than `$DSH_AGENTS_HOME`: an env var only reaches shells that export it, and a dsh started from a desktop entry or a unit was getting the whole tree. |
| pi | Skills: no view is possible (it hardcodes `$HOME/.agents/skills`), so its own `!<glob>` **excludes** are generated instead. Commands: `~/.pi/agent/prompts` points at a rendered view, because a command can be claude-only too. |

Two consequences worth knowing. A tag exclusion is applied at *render* time, so an
excluded skill never reaches the harness's context at all — that is the point for
`homelab` on a work machine. And because views are symlink farms, editing a skill is live,
while adding or removing one needs a re-render (any `bootstrap sync` does it).

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

## Checking it

```sh
bin/check.sh
```

Index currency, every skill against the strictest parser (dsh requires both `name`
and `description` — it has no directory-name fallback), the policy regexes
compiled under **both** engines, the skill unit tests, and a guard that no
globally-scoped artifact references a path only the setup repo has. There is no
CI here yet, so this is the gate; run it before pushing.

## Adding something

1. Pick the scope: portable → here; about one repo → that repo's `.agents/`.
2. Add `harness:` only if it genuinely cannot run everywhere; add `tags:` for anything a
   machine might want to opt out of wholesale (`homelab` is the live example).
3. Runtime assets → `lib/<name>/`, referenced as `~/.agents/lib/<name>/…`.
4. `uv run --script bin/agents-index.py --write`, and commit the index with the skill.
5. On each machine, `bootstrap sync` re-renders the views.

Design record: `docs/superpowers/plans/2026-08-31-fleet-consolidation-analysis.md` in the
setup repo.

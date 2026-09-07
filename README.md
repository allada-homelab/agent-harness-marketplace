# agent-harness-marketplace

One content tree, three harnesses. Every module under `modules/<name>/` installs
natively on **Claude Code**, **pi** (`@earendil-works/pi-coding-agent`) and **dsh**
(`@deepseek-ai/dsh`) from the same directory: the shared content is Agent Skills
(`skills/<skill>/SKILL.md`), and each harness reads its own thin manifest beside it.

| Harness | Install | Update | Narrow |
|---|---|---|---|
| Claude Code | `/plugin marketplace add allada-homelab/agent-harness-marketplace` then `/plugin install <module>@agent-harness-marketplace` | bump the module's version | `skillOverrides` in settings |
| pi | `pi install git:github.com/allada-homelab/agent-harness-marketplace@vX.Y.Z` (the repo root is the pi package) | `pi install …@vNext` | `settings.packages[{source, skills: ["!modules/<n>/**"]}]` |
| dsh | `dsh plugin --profile <p> add "github:allada-homelab/agent-harness-marketplace#vX.Y.Z&path:/modules/<module>"` per module | re-add at the new ref | install only what you want |

Per-harness walkthroughs with the exact commands and their output on a fresh
install: [docs/install-claude.md](docs/install-claude.md),
[docs/install-pi.md](docs/install-pi.md), [docs/install-dsh.md](docs/install-dsh.md).

## Modules

`modules/index.yaml` is the generated catalog: every module, which harnesses it
applies to, and every skill with its `harness:` / `tags:` selection metadata.

Content modules (skills only, no code):

- **minimalist-code-review** — a pragmatic, anti-over-engineering PR reviewer.
- **get-shit-done** — the method for decomposing a big task and delegating each
  piece to the cheapest capable model. `get-shit-done-claude` adds the
  `/get-shit-done-claude:run` Workflow driver (Claude Code only).
- **research** — `/research <topic>`: the research-before-acting ladder as a step.
- **claude-transcripts**, **dual-agent-pr-review** — Claude Code only.

The harness-side foundation that content modules need to run on a given
harness (the dsh skills bridge, the pi and dsh hook runners, and pi's `/name`
commands) is no longer part of this repo: it lives in
the maintainer's dotfiles harness layer (a private repo; not published here)
under `agents/harnesses/`, always installed there. This repo ships
user-facing modules only. The hook contract's prose stays in
[`hook-contract/README.md`](hook-contract/README.md); its executable corpus
now lives beside the runners in that repo.

## Authoring

Commands are skills: a `SKILL.md` with `user-invocable: true` and an
`argument-hint` is `/name` on Claude, `/skill:name` (or `/name` with
skill-commands-pi) on pi, and `/name` on dsh through the bridge. The portable
contract — which frontmatter keys survive all three parsers, why assets are
referenced skill-relative, when to scope a skill with `harness: [claude]` — is
in [docs/authoring.md](docs/authoring.md) and enforced by `bin/lint-skills.py`.
Everything the repo can verify about itself runs from one command:

```
bin/check.sh
```

## Versioning

Git tags `vX.Y.Z` are what pi and dsh install. Each module carries its own
version in `package.json`, `.claude-plugin/plugin.json` and its
`.claude-plugin/marketplace.json` entry; `bin/check.sh` fails when they disagree.

## History

Until 2026-09-01 this repository held a `~/.agents` tree of skills and shared
policy; that tree was folded into its owner's dotfiles, and the marketplace was
rebuilt here from scratch on 2026-09-06 with the layout above.

# agent-harness-marketplace

One content tree, three harnesses. Every module under `modules/<name>/` installs
natively on **Claude Code**, **pi** (`@earendil-works/pi-coding-agent`) and **dsh**
(`@deepseek-ai/dsh`) from the same directory: the shared content is Agent Skills
(`skills/<skill>/SKILL.md`), and each harness reads its own thin manifest beside it.
Every module also carries a generated [Agent Plugins v1](https://agent-plugins.org)
`plugin.json`, so it installs in Cursor, Codex, Copilot, Kiro and VS Code too.

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

- **plan-for-dummies** — write an implementation plan a weaker model can execute
  without the planner present.
- **agent-transcripts** — export Claude Code, pi and dsh transcripts into one
  on-device cache and index them in a derived sqlite database.
- **browser** — drive a browser from any harness: headless, or headed so a human
  logs in and the agent takes over.
- **dual-agent-pr-review** — Claude Code only.

Modules that also ship `agents/` or `hooks/`:

- **code-review** — parallel reviewers from five lenses, confidence scoring, one
  comment posted with `gh`.
- **feature-dev** — guided seven-phase feature development; a harness-neutral
  port of Anthropic's plugin whose agents dispatch on all three harnesses.
- **pr-flow** — branch + worktree, PR, watch CI until green, merge only when told.

The harness-side foundation that content modules need to run on a given
harness (the dsh skills bridge, the pi and dsh hook runners, and pi's `/name`
commands) is no longer part of this repo: it lives in
the maintainer's dotfiles harness layer (a private repo; not published here)
under `agents/harnesses/`, always installed there. This repo ships
user-facing modules only. The three author-facing contracts stay here —
[`hook-contract/`](hook-contract/README.md), [`agent-contract/`](agent-contract/README.md)
and [`workflow-contract/`](workflow-contract/README.md), for `hooks/hooks.json`,
`agents/*.md` (and forked skills) and `workflows/*.js` — while the executable
corpus each one holds its runners to now lives beside them in that repo.

## Authoring

Commands are skills: a `SKILL.md` with `user-invocable: true` and an
`argument-hint` is `/name` on Claude, `/skill:name` on pi (`/name` through the pi
harness's skill-commands foundation extension), and `/name` on dsh through the
harness's skills bridge. The portable
contract — which frontmatter keys survive all three parsers, why assets are
referenced skill-relative, when to scope a skill with `harness: [claude]` — is
in [docs/authoring.md](docs/authoring.md) and enforced by `bin/lint-skills.py`.
The procedure around it — the manifests that must agree, the generated files, the
traps — is the repo-scoped skill in
[`.agents/skills/adding-a-module/`](.agents/skills/adding-a-module/SKILL.md).
Everything the repo can verify about itself runs from one command:

```
bin/check.sh
```

## Versioning

Git tags `vX.Y.Z` are what pi and dsh install. Each module carries its own
version in `package.json`, `.claude-plugin/plugin.json` and its
`.claude-plugin/marketplace.json` entry; `bin/check.sh` fails when they disagree.

The repo tag is cut automatically: a merge to `main` that changed anything under
`modules/` gets the next patch tag once `check` and `smoke` are green. A merge
that changed only docs, CI or repo tooling ships nothing installable and gets no
tag. Patch is the only automatic step — push a tag by hand to move the minor or
major, and the next automatic tag continues from it.

## History

Until 2026-09-01 this repository held a `~/.agents` tree of skills and shared
policy; that tree was folded into its owner's dotfiles, and the marketplace was
rebuilt here from scratch on 2026-09-06 with the layout above.

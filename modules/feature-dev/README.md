# feature-dev

Guided seven-phase feature development: explore the codebase with parallel
specialist agents, ask clarifying questions, compare architectures, implement,
then review. One skill, `/feature-dev [description]`, drives the flow; three
agents do the isolated work.

| Agent type | Role | Tools on Claude / pi / dsh |
|---|---|---|
| `feature-dev:code-explorer` | Trace an existing feature or area comprehensively; return key files | read-only: Glob, Grep, LS, Read (+ web on Claude) / `find grep ls read` / `glob grep read` |
| `feature-dev:code-architect` | Design an implementation blueprint with a stated focus | same |
| `feature-dev:code-reviewer` | Review for bugs, simplicity or conventions with confidence filtering | same |

## Install

- **Claude Code**: enable the `feature-dev` plugin from this marketplace and
  disable the official `feature-dev@claude-plugins-official` if it is enabled,
  or both `/feature-dev` and the three agent types register twice.
- **pi**: `pi install git:github.com/allada-homelab/agent-harness-marketplace`
  gives you the skill. The agents dispatch through the `delegate_agent` tool
  that the pi harness's `module-agents` foundation extension provides; without
  it the skill runs each phase inline.
- **dsh**: install the module as a bundle. The dsh harness's `module-agents`
  bridge exposes the agents through `delegate_agent`; the skill arrives through
  the skills bridge like every other module.

## How the agents cross harnesses

`agents/*.md` are Claude Code subagent files, unmodified from upstream. Claude
reads them natively. pi and dsh read the same files through a generic bridge
held to [`agent-contract/`](../../agent-contract/README.md): the body becomes
the child's system prompt, `tools` translates to native tool names (unknown
Claude tools are dropped), `model: sonnet` resolves through the harness's
alias map or inherits the parent's model. Children are foreground-only on pi
and dsh in this version.

## Provenance

Ported from Anthropic's `feature-dev` plugin in
`anthropics/claude-plugins-official` at commit `76b35e9`, Apache-2.0 (see
`LICENSE`). Changes from upstream: `commands/feature-dev.md` became
`skills/feature-dev/SKILL.md`; the TodoWrite instruction became
harness-neutral; a "Dispatching the specialist agents" section names the
per-harness delegation tool and a sequential fallback; agent names are
written as `feature-dev:<agent>` types. The three agent files are verbatim.

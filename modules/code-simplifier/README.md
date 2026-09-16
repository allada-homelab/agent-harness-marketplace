# code-simplifier

Simplify recently changed code on every harness. Ships the `code-simplifier`
skill (`/code-simplifier` on Claude Code and dsh, `/skill:code-simplifier` on
pi) and the one subagent it dispatches — `code-simplifier:code-simplifier` —
through the Agent tool on Claude Code and `delegate_agent` on pi and dsh.

What a run does:

1. resolves the scope — the arguments you gave, else the uncommitted changes,
   else the branch's diff against the default branch;
2. the agent reads the project's guideline files (`CLAUDE.md`, `AGENTS.md`)
   and the surrounding code for the conventions in force;
3. it edits the scoped code in place: less nesting, no redundant abstractions,
   clearer names, no nested ternaries, clarity over brevity — never a change
   in behavior, never a touch outside the scope;
4. it reports the files changed and each significant refinement. Nothing is
   committed; you review the diff.

## Install

- Claude Code: `/plugin marketplace add allada-homelab/agent-harness-marketplace`
  then `/plugin install code-simplifier@agent-harness-marketplace`
- pi: install the marketplace package; the skill is globbed in by the root
  manifest.
- dsh: add the bundle; the harness's skills and agents bridges discover the
  skill and the agent.

## Provenance

A port of the `code-simplifier` plugin from
`anthropics/claude-plugins-official` (Apache-2.0; the agent body derives from
that work). What changed to make it portable:

- `model: opus` is gone: the module is model-agnostic and the agent inherits
  the session's model on all three harnesses;
- the hardcoded house style (ES modules, `function` over arrows, React Props
  types) became "read the project's `CLAUDE.md` / `AGENTS.md` and match the
  surrounding code" — the upstream list was Anthropic's own repo convention;
- "recently modified code" is now resolved concretely through `git`;
- the agent has an explicit `tools:` list and a report format;
- a user-invocable skill wraps the agent so pi and dsh, which have no
  proactive agent triggering, can run it on demand. The upstream agent's
  "run proactively after every edit" behavior is not carried: it is
  Claude-specific and the skill is the portable entrypoint.

The refinement principles, the balance rules and the scope discipline are
unchanged.

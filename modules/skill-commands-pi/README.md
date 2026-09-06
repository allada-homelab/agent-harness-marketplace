# skill-commands-pi

`/name args` for skills that declare `user-invocable: true`.

pi already exposes every loaded skill as `/skill:name` (see pi's
`docs/skills.md`, "Skill Commands"). In this marketplace **commands are
skills** — a user-invocable `SKILL.md` is the command — so on Claude Code the
same file is `/name`. This extension registers that short alias on pi for the
subset of skills that opt in:

```yaml
---
name: research
description: …
user-invocable: true
---
```

`/research some topic` then behaves exactly like `/skill:research some topic`.
Skills without the field are untouched and remain available as `/skill:name`
and to the model.

## How it works

- **Enumeration:** at `session_start`, `pi.getCommands()` — the only skill
  enumeration available to an extension that also carries each skill's
  `SKILL.md` path (`sourceInfo.path`). Entries with `source === "skill"` are
  named `skill:<name>`.
- **The filter:** pi's own `Skill` object keeps only `name`/`description`/
  `filePath`/`baseDir`, so `user-invocable` is read from the file with a
  minimal frontmatter parse.
- **The expansion:** replicated, not called. `pi.sendUserMessage` routes
  through `AgentSession.prompt(text, { expandPromptTemplates: false })`
  (`dist/core/agent-session.js:1128-1132`), so sending `"/skill:name args"`
  through it would reach the model verbatim. The handler therefore builds the
  same `<skill name=… location=…>` block `AgentSession._expandSkillCommand`
  builds (`dist/core/agent-session.js:949-975`) and sends that. The file is
  re-read at invocation, so editing a skill mid-session takes effect. **If pi
  changes that block format, this copy has to change with it.**
- **Collisions:** pi would keep both registrations and suffix ours `/name:1`,
  which is not the alias anyone typed. A name already present in
  `pi.getCommands()` is declined instead, with one line on stderr naming the
  `/skill:name` fallback.

Event-only aside from the commands themselves: no `registerTool`, no prompt
text, 0 tokens per turn.

## Install

```bash
pi install git:github.com/allada-homelab/agent-harness-marketplace@v1
```

Loaded by the repo-root pi package manifest
(`pi.extensions: ["modules/*/extensions/*.ts"]`).

## Test

```bash
cd modules/skill-commands-pi && npm test
```

`node --test` bundles the extension with `npx esbuild` and exercises the
frontmatter filter, the expansion, and the registration wiring against a fake
pi API. If esbuild cannot be obtained the suite fails rather than skips.

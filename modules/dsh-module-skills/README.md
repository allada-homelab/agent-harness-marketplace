# dsh-module-skills

Make a marketplace module's `skills/` directory visible to dsh.

## The problem

dsh discovers skills from a fixed set of roots and nothing else
(`@deepseek-ai/dsh-skill-filesystem`, `roots()`):

- `<project>/.dsh/skills`
- `<project>/.agents/skills`
- `customSkillDirs` (host config)
- `<dshHome>/skills`
- `<agentsHome>/skills`

A module installed with `dsh plugin add` lands in the profile's `node_modules`,
where none of those roots reach. Its `skills/` directory is invisible: the model
never sees the catalog entry and `/name` resolves to nothing.

This module is the generic bridge that closes that gap, once, for every content
module in the marketplace. It is skills-only — it spawns no process, reads no
hook manifest, and gates on no trust list. It reads Markdown and hands text to
two dsh registries.

## What it does

1. **Registers one `ctx.skills` provider** over every module skill root it
   finds, so module skills join the normal dsh catalog with normal precedence.
   `resourceBase` is set to each skill's own directory, so a body that says
   `./scripts/check.py` resolves against the skill bundle rather than the root.
2. **Registers a `/name` command** for each user-invocable skill whose body uses
   `$ARGUMENTS` or `$N`, because dsh's native slash path does not substitute
   arguments (see below). Skills without those tokens are left to dsh's own
   path, which serves them better. `metadata.dsh-command` overrides that
   guess — see below.
3. **Watches every root.** A skill added, edited, or removed after boot
   invalidates the catalog (`SkillProviderControl.invalidate`) after a ~300 ms
   debounce, so `dsh plugin add` or an edit in your checkout shows up without a
   restart. `fs.watch` is used recursively where the platform supports it and
   per-directory otherwise. Watching is a convenience: a root that cannot be
   watched costs one `stderr` line and keeps all of its skills.

### Precedence

Candidates carry `rank: 600`, matching dsh's own `BUNDLED_SKILL_RANK`. A
project, custom, or user skill of the same name (ranks 100–500) always wins over
one a module shipped.

### The `harness:` key

`harness: [claude, pi, dsh]` is this repo's convention; every harness's own
loader ignores it. This bridge honors it: a skill whose `harness` list omits
`dsh` never reaches the dsh catalog.

### What happens to a broken skill

Nothing else breaks. A malformed skill drops with one line on `stderr`, a
broken root drops with one line, and `apply()` never throws — a bad module must
not stop a session from starting. Lines go to `process.stderr` rather than
`ctx.logger` because the logger does not reach journald on a service-managed
dsh.

## Arguments: what dsh does and does not do

Verified against dsh 0.1.1-rc.2:

| Step | Where | Behavior |
| --- | --- | --- |
| Pick a skill from the `/` menu | `@deepseek-ai/dsh-client-ui-skill` `lib/client.js`, the trigger source's `onPick` | types `/<name> ` into the composer — nothing more |
| Submit the line | `@deepseek-ai/dsh-tool-skill` `lib/index.js:352`, `invokedSkillNames` :360 | matches the bare gesture `(^|\s)\/([a-z0-9]+(?:-[a-z0-9]+)*)(?=\s|$)` |
| Inject | same file, :163–170 | injects the body **verbatim** via `renderSkillContent` |

So the user's typed arguments reach the model only as their own plain user
message; nothing substitutes them into the body. That is the whole reason the
command half of this plugin exists. Its expansion rules:

- `$ARGUMENTS` — the entire argument string, trimmed.
- `$N` — the N-th word, quote-aware (`/review main "two words"` → `$2` is
  `two words`). An unsupplied `$N` is left **verbatim**, so a body that mentions
  `$1` in a shell snippet still reads correctly on a bare invocation.
- `${N:-default}` — the N-th word, or the default.
- `$HOME`, `${PATH}` and every other shell-looking token are never touched.

The expanded body is sent as the user turn through
`agent.followup(createUserMessage(...))` — the same seam dsh's own `/goal`
command uses.

The message is minted here rather than imported. `followup` needs an identified
message, and dsh's own `createUserMessage` adds exactly `role: 'user'` and
`id: randomUUID()` before freezing (`@deepseek-ai/dsh-llm` `lib/index.js:157-176`),
so this plugin builds the same object with `node:crypto`. Importing it used to
be the implementation and was a real bug: `@deepseek-ai/dsh-llm` resolves for a
package installed *into* the profile but not for a `link:`/repo-resident
install, which parent-walks out of the profile — so every command silently
disappeared on exactly the install shape a module author develops against.

### Opting a skill in or out of a command

Token detection is a heuristic, and `$5 million` in prose looks exactly like a
positional argument. `metadata.dsh-command` settles it:

```yaml
---
name: budget-review
description: Reviews a budget.
metadata:
  dsh-command: false   # never register a /command, whatever the body contains
---
```

`true` forces registration even for a token-free body — the case where you want
the argument string carried along rather than substituted. Anything else is one
`stderr` line and a fall back to token detection. `metadata` is the portable
frontmatter key every harness carries through untouched, so this costs the skill
nothing on Claude or pi.

## Install

```
dsh plugin --profile <profile> add "github:allada-homelab/agent-harness-marketplace#v0.1.0&path:/modules/dsh-module-skills"
```

`dsh plugin` forwards to pnpm in the profile directory and then reconciles
`dsh.profile.bundles`: any installed dependency whose manifest declares
`dsh.bundle` joins the layer stack automatically. This package declares one, so
after the install its row is mounted and every bundle in the profile that ships
a `skills/` directory is served.

## Configuration

The row's `config` accepts:

| Key | Default | Meaning |
| --- | --- | --- |
| `dirs` | `[]` | Absolute paths to additional `skills/` directories (a checkout, a dotfiles tree). Relative entries are refused with one line. |
| `bundles` | *(all)* | Restrict auto-discovery to these package names. |
| `autoDiscover` | `true` | Set `false` to serve only `dirs`. |
| `providerName` | `module-skills` | The `ctx.skills` provider label. Must be unique — dsh throws on a duplicate provider name within one layer. |
| `profileDir` | *(from `ctx.baseUrl`)* | Override the profile directory used for auto-discovery. |
| `commands` | `true` | Set `false` to register skills only, no slash commands. |

Roots are deduplicated by realpath, so a `dirs` entry and an auto-discovered
bundle that are the same directory (a pnpm link, a symlinked checkout) register
once.

### How the profile directory is found

dsh boots a profile by calling `boot(NAME, <profileDir>/cordis.root.yml, …)`,
which sets `ctx.baseUrl = pathToFileURL(dirname(configPath))`
(`@deepseek-ai/dsh-app-boot` `lib/index.js:1171`). That is the same directory
`dsh plugin` installs into (`resolveProfileDir` :318 =
`<dshHome>/profiles/<name>`), so the profile manifest and its `node_modules`
are both reachable from `ctx.baseUrl`.

## How a content module uses this

A content module ships its own `cordis.patch.yml` that inserts one row of *this*
plugin, so dsh's `reconcilePlugins` picks the module up when it is installed.
Copy `docs/content-module-cordis.patch.yml` and replace `<module>` with the
module's directory name. The exact row:

```yaml
- insert:
    - id: module-skills-<module>
      name: '@allada-homelab/dsh-module-skills'
      config:
        providerName: module-skills-<module>
        bundles:
          - '@allada-homelab/<module>'
        dirs: []
```

The content module does not declare the bridge as a dependency: install
`dsh-module-skills` once per profile (above) and every content module's row
resolves it from there.

`id` and `providerName` must be module-specific: two modules inserting the same
row id collide in the loader tree, and two providers registering the same name
collide in `ctx.skills`. `bundles` keeps each module's row serving only its own
skills instead of rescanning every module's.

## Tests

```
node --test test/*.test.mjs
```

No dependencies, at runtime or in test. The front-matter parser is a deliberate
YAML subset (`lib/frontmatter.js`) rather than a `yaml` dependency, so this
module adds nothing to the marketplace's install surface.

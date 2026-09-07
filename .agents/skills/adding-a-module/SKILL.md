---
name: adding-a-module
description: How to add a new module, or a new skill to an existing module, in the agent-harness-marketplace repo — the exact files, the manifests that must agree, the generated files to regenerate, and the checks that must pass. Use when creating or modifying anything under modules/, when bin/check.sh fails, or when asked to "add a skill/plugin/module" to this repo.
---

# Adding to agent-harness-marketplace

One content tree, three harnesses. Every module under `modules/<name>/` installs
natively on Claude Code, pi and dsh from the same directory: the shared content
is Agent Skills (`skills/<skill>/SKILL.md`), and each harness reads its own thin
manifest beside them.

**Read `docs/authoring.md` first.** It is the portable `SKILL.md` contract — which
frontmatter keys survive all three parsers, why assets are skill-relative, when to
scope with `harness: [claude]`. This skill does not repeat it; it covers the
procedure around it and the failures that contract doesn't catch. Every path below
is relative to the repo root.

## Decide what you are adding

| You are adding | Do this |
|---|---|
| A skill to an existing module | Create `skills/<skill>/SKILL.md`, bump that module's version everywhere it appears (`package.json`, and `plugin.json` + the marketplace entry if it has them), regenerate the index, verify. |
| A new module | Full procedure below. |
| Hooks | `hooks/hooks.json` in Claude's shape, `"type": "command"` handlers, event keys drawn from `hook-contract/events.json`, and every `CLAUDE_PLUGIN_ROOT`-prefixed command path resolving to a file that ships in the module. Read `hook-contract/README.md` for the stdin/stdout contract and the two fidelity gaps. |
| A pi extension (`extensions/`) or dsh plugin code (`lib/`) | **Stop and ask.** The conformance tests currently forbid both outright — `tests/conformance/pi.test.mjs` and `dsh.test.mjs` assert no module contains either. The harness-side foundation left this repo; reintroducing executable code is a repo-shape decision, not a module change. |

## New module, step by step

### 1. Name it

The directory name is the identity and three files must agree with it:
`modules/<name>/`, `plugin.json` `"name": "<name>"`, `package.json`
`"name": "@allada-homelab/<name>"`. A skill directory's name must equal its
`SKILL.md` frontmatter `name`.

### 2. Create the files

```
modules/<name>/
  package.json                     # every module needs one; it carries the version
  .claude-plugin/plugin.json       # only if Claude should install it as a plugin
  cordis.patch.yml                 # required whenever the module has skills/ or a dsh key
  README.md                        # convention: every module has one
  skills/<skill>/SKILL.md
  skills/<skill>/references/*.md   # optional assets, referenced skill-relative
```

`package.json` — copy this, changing name/description:

```json
{
  "name": "@allada-homelab/<name>",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "description": "<one line; this becomes the module description in modules/index.yaml>",
  "license": "MIT",
  "pi": { "skills": ["skills/*"] },
  "dsh": { "bundle": { "patch": "./cordis.patch.yml" } }
}
```

`.claude-plugin/plugin.json` — the version must match `package.json` exactly:

```json
{
  "name": "<name>",
  "version": "0.1.0",
  "description": "<same one line>",
  "author": { "name": "David Allada", "email": "davidanilallada@gmail.com" },
  "license": "MIT"
}
```

`cordis.patch.yml` — for a **content module** (has `skills/`, no `lib/`) this file
must be **empty**. The file must exist and `package.json` must carry the
`dsh.bundle.patch` key; dsh installs a package without that key as a plain
dependency and silently ignores the patch.

```yaml
# Empty on purpose. This module is a dsh BUNDLE (package.json `dsh.bundle`)
# so the harness lists it in the profile's dsh.profile.bundles — and the
# always-installed skills bridge in the maintainer's harness layer discovers
# every bundle that ships skills/. Nothing to insert.
[]
```

### 3. Add the marketplace entry

A module with `.claude-plugin/plugin.json` **must** have an entry in the repo's
`.claude-plugin/marketplace.json`, with the same version and
`"source": "./modules/<name>"`. A module without `plugin.json` must **not** have
one. Both directions fail the check.

```json
{
  "name": "<name>",
  "description": "<same one line>",
  "category": "development",
  "version": "0.1.0",
  "source": "./modules/<name>"
}
```

### 4. Reconcile the root pi manifest

pi installs the whole repo, so the **root** `package.json` `pi.skills` decides
what every pi user gets:

- If **any** skill in the module applies to pi (no `harness:` key means all three),
  leave the root manifest alone — `modules/*/skills/*` already globs it in.
- If **every** skill is scoped away from pi (`harness: [claude]`, say), add
  `"!modules/<name>/**"` to the root `pi.skills` array.

Getting this backwards fails in both directions.

### 5. Regenerate the index

`modules/index.yaml` is generated — never hand-edit it.

```
uv run --script bin/render-index.py --write
```

Module `description` comes from the module's `package.json`; each skill's
`summary` is the **first sentence** of its `SKILL.md` `description`, so write that
first sentence to stand alone.

### 6. Verify

```
bin/check.sh                              # the deterministic gate
CHECK_BASE=origin/main bin/check.sh       # + the changed-module version-bump rule
bin/check.sh --no-node                    # same minus the pnpm/node suites
```

`bin/check.sh` is **not** all of CI. Three things differ locally:

- The **smoke job is separate** and `check.sh` never invokes it. To reproduce:
  `npm install -g @earendil-works/pi-coding-agent @deepseek-ai/dsh`, then
  `bash tests/smoke/pi.sh` and `bash tests/smoke/dsh.sh`.
- The **version-bump-on-change** step is inert unless you set `CHECK_BASE`; CI
  always sets `origin/main`.
- **`claude plugin validate`** is silently skipped when the `claude` CLI is not on
  PATH locally, but hard-fails in CI.

Capture the baseline before you start: a failure in a module you did not touch is
not yours to fix in this change, but you must say so rather than report a green
gate.

### 7. Ship

Branch off `main`, one atomic commit, open a PR. CI runs `check` (that is
`CHECK_BASE=origin/main ./bin/check.sh`, full, no `--no-node`) and `smoke` (pi and
dsh installed from npm for real). Both must be green.

## Traps

These pass a casual reading and fail the gate:

- **Do not copy `cordis.patch.yml` from an older module without reading it.**
  Content modules used to carry loader `insert:` rows; since the harness-side
  foundation left this repo the file must be empty. A stale copy fails
  `content modules: empty dsh patch`.
- **`plugin.json` and the marketplace entry travel together**, at the same
  version as `package.json`. Three places, one version.
- **The asset-exists lint only fires on paths written with a `./` prefix.**
  `references/x.md` in a SKILL.md body is *not* checked and will ship broken;
  write `./references/x.md`.
- **Never hand-edit `modules/index.yaml`** — regenerate it, or the
  `index.yaml is current` step fails.
- **No absolute or `~/` paths** anywhere under `modules/`, `docs/` or `README.md`,
  and no homelab hostnames or RFC1918 addresses. There is a grep for it.
- **A changed module must bump its version.** CI checks this against
  `origin/main`; locally the step is skipped unless `CHECK_BASE` is set. pi and
  dsh install at a tag, so an unbumped change is invisible to them.
- **`harness:` unlocks the Claude-only keys only when the scope is *exactly*
  `[claude]`.** `harness: [claude, pi]` still gets every portability check, so
  `allowed-tools`, `model`, `CLAUDE_*` placeholders, absolute paths and
  bang-backtick shell injection all still fail there.
- **Never write a bang immediately followed by a backtick in any SKILL.md body,
  even inside a code span.** Claude Code's skill loader executes it as a shell
  command at load time and the skill fails to load — a stricter rule than the
  repo lint, which only catches it at the start of a line.
- **A `description` over 1024 characters fails the lint** — pi sends it on every
  request of the agentic loop.
- **Leftover `node_modules/` in a deleted module's directory** makes `check.sh`
  treat it as a module missing its `package.json`. Remove the stale directory.

# agent-harness-marketplace

One content tree, three harnesses. Every module under `modules/<name>/` installs
natively on Claude Code, pi and dsh from the same directory. The shared content is
Agent Skills (`skills/<skill>/SKILL.md`); each harness reads its own thin manifest
beside them. This repo ships user-facing modules only — the harness-side
foundation lives in the maintainer's dotfiles layer.

## Before changing anything under `modules/`

Read the `adding-a-module` skill (`.agents/skills/adding-a-module/SKILL.md`). It
has the procedure, the manifests that must agree, and the traps. `docs/authoring.md`
has the portable `SKILL.md` contract. Do not reconstruct either from memory.

## Constraints that bite

- **`modules/index.yaml` is generated.** Never hand-edit it; run
  `uv run --script bin/render-index.py --write`.
- **A module's version lives in three files** (`package.json`,
  `.claude-plugin/plugin.json`, and its `.claude-plugin/marketplace.json` entry)
  and they must agree. A changed module must bump it — pi and dsh install at a
  tag, so an unbumped change is invisible to them.
- **A content module's `cordis.patch.yml` must be empty.** Older modules carried
  loader rows; copying one now fails the gate.
- **`extensions/` and `lib/` are forbidden** by `tests/conformance/`. Reintroducing
  executable code is a repo-shape decision — stop and ask.
- **Skills are portable by default.** No `allowed-tools`, `model`, `CLAUDE_*`
  placeholders, absolute or `~/` paths, or bang-backtick shell injection unless
  the skill is scoped `harness: [claude]` — and that unlocks them only when the
  scope is *exactly* `[claude]`. Claude Code's loader executes a bang-backtick
  sequence at load time even inside a code span, so never write one in any body.
- **No private paths** — no absolute paths, homelab hostnames or RFC1918
  addresses anywhere under `modules/`, `docs/` or `README.md`. There is a grep.

## Verify before claiming done

```
bin/check.sh                          # the deterministic gate; CI runs exactly this
CHECK_BASE=origin/main bin/check.sh   # + the changed-module version-bump rule
bin/check.sh --no-node                # same minus the pnpm/node suites
```

`bin/check.sh` is not all of CI: the `smoke` job (real pi and dsh installed from
npm, `tests/smoke/`) runs separately and `check.sh` never invokes it. Capture the
baseline first — a failure in a module you did not touch is not yours to fix, but
say so rather than reporting a green gate.

## Repo-scoped agent resources

Project skills live in `.agents/skills/<name>/SKILL.md` so all three harnesses
read them; `.claude/skills` is a relative symlink onto that directory. Do not add
`.claude/commands/` (Claude would register the command twice) or an `AGENTS.md`
beside this file (dsh loads both and injects the text twice).

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

- **`modules/index.yaml` and every `modules/<name>/plugin.json` are generated.**
  Never hand-edit them; run `uv run --script bin/render-index.py --write` and
  `uv run --script bin/render-plugin-manifests.py --write`.
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
- **Agent `tools:` (and a forked skill's `allowed-tools:`) is written in Claude's
  tool names and translated per harness — a name a harness does not have is
  dropped with one warning line, by design, and never an error.** This is the
  documented `agent-contract` behavior. Our standing decision is to keep the
  full tool list and embrace the drop-with-a-warning rather than trim to the
  intersection that exists on every harness: the dropped names are informational
  (pi runs and exits 0; dsh omits `toolFilter`), the read-only capability the
  agent actually uses is unaffected, and it lets one file declare harness-
  specific tool spellings (e.g. `read-image` and `ReadImage`) so each harness
  uses the name it knows. Do not trim a `tools:` list purely to silence the
  startup warning.
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

## Pairing with the fleet

This repo publishes; it installs nothing. The maintainer's dotfiles repo
(`.davidallada-developer-setup`, private) consumes it through one file,
`agents/modules.tsv` — a row per module pinning this repo at a **tag** and
switching it on or off per harness — rendered by `render-modules.py` into
`claude/settings.json`, `pi/settings.json` and every dsh profile. A change here
is live on the fleet only after the paired dotfiles change. Six cases need one:

1. **New module** → a `modules.tsv` row, or the fleet never installs it.
2. **Any merge under `modules/`** → it cuts a tag; the fleet stays on its old
   pin until the `ref` column is bumped and re-rendered.
3. **A port of an official Claude plugin** → disable `<name>@claude-plugins-official`
   in the fleet's `claude/settings.json`, or Claude registers the skill twice.
4. **Removed module** → turn its row `off off off`; never delete it. The row is
   what keeps pi's `!modules/<m>/**` exclude across a failed ref move (the old
   clone stays loadable) and gives the renderer a key to retract.
5. **A contract change** (`agent-contract/`, `hook-contract/`,
   `workflow-contract/`, the `mcp.json` rules) → the executable corpus and the
   bridges live in dotfiles `agents/*-contract/`; land there first, then here.
6. **A skill that needs a bridge feature that does not exist yet** (a new tool
   mapping, dispatch shape, event) → a bridge change in dotfiles before the
   module may rely on it.

Skill bodies, docs, generated manifests, tests and lone version bumps need no
pairing; they ride the next pin bump. `bin/check.sh` runs
`bin/fleet-pairing.sh`, which reads the dotfiles declaration when it is on this
machine and **warns** (never fails) on cases 1–4. Every handoff that touches
`modules/` or a contract names the paired dotfiles change it needs, or says none.

## Repo-scoped agent resources

Project skills live in `.agents/skills/<name>/SKILL.md` so all three harnesses
read them; `.claude/skills` is a relative symlink onto that directory. Do not add
`.claude/commands/` (Claude would register the command twice) or an `AGENTS.md`
beside this file (dsh loads both and injects the text twice).

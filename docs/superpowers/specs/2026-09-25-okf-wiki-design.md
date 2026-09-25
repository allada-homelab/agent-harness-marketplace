# okf-wiki — design

Date: 2026-09-25. Status: design reviewed section by section in session; this file awaits
review before an implementation plan is written.

Supersedes `docs/planning/wiki/decisions.md` (D-01..D-12). That directory stays as the OKF
research record; its "no hooks, no scripts" premise was wrong — modules may ship
`hooks/hooks.json` with command scripts (`hook-contract/README.md`, `modules/pr-flow/hooks/`).

## Goal

One module, `modules/okf-wiki/`, that gives every repo a small, trustworthy, self-healing
knowledge bundle in Open Knowledge Format v0.2 at `<repo>/.wiki/`, which agents on Claude
Code, pi and dsh consult before work and add to as they learn — unprompted, in the
background where the harness allows, on cheaper models. A `reflect` loop measures whether
the wiki and its prompting are actually effective and proposes fixes.

"Relatively simple but next level" means: only knowledge the code cannot tell you; every
concept checkable against the code; knowledge repairs itself where it is used; scripts do
everything deterministic; models do judgment only.

## Prior art and what we took from it

- **public-skills `plugins/llm-wiki`** (Claude-only, ~6.8k lines Python + 2.6k tests vs ~1.5k
  lines prompt). Kept: OKF contract, upsert capture, forked cited recall, `## Verify`
  anchors, flat-first layout, claim-style descriptions, "main agent judges, cheap agent
  persists". Rejected: job controller, packet contracts, recall routing/lenses, gap
  research, sentinels, entropy secret scan, per-project markers. Its field bugs clustered in
  exactly the rejected layer. Evidence it recorded: retrieval is an agent reading markdown;
  value is on non-obvious/runtime knowledge (gotcha test 11/12 → 12/12), near zero on
  grep-able facts; the worst failures were "agents never consult" and silent failure.
- **Upstream OKF** (`docs/planning/wiki/okf-upstream/`, `reference-implementations.md`):
  deterministic `index.md` algorithm, write guards, concept-id regex, `acme_retail` fixture.

## Decisions

| # | Decision | Choice | Why |
|---|---|---|---|
| 1 | Scope | One bundle per repo; recall takes a list of bundle roots so a global bundle can be added later | Per-repo knowledge is verifiable against its code; that is where measured value was. |
| 2 | Location | `<repo>/.wiki/` | Tooling-owned, matches `.claude/`, `.remember/`. |
| 3 | Write posture | Automatic, with a visible one-line receipt | Confirm-first was abandoned by llm-wiki; receipts + git keep it reversible. |
| 4 | Unprompted trigger | Rule injected at SessionStart + a gated Stop nudge | Content alone relies on memory at task end; per-edit nudges nag. |
| 5 | Read path | SessionStart injects a compact digest; forked cheap `recall` for depth | The read loop is the product; full fidelity on all three harnesses. |
| 6 | Concept shape | Flat; closed types `gotcha, decision, runbook, convention, architecture`; claim descriptions; capture bar "not recoverable by grepping the code" | Open vocabularies drifted; code restatements had no value. |
| 7 | Freshness | `## Verify` anchors + `verified[].commit`; git-based STALE at recall; scribe heals | Knowledge repairs itself where it is used; time-based TTLs are a poor proxy. |
| 8 | Derived files | Hooks rebuild `index.md` deterministically and validate loudly; models never write it | Model-written indexes drift. |
| 9 | Bootstrap | History-mined `ingest` (commits, PRs, docs, existing bundles incl. llm-wiki migration) | The non-obvious knowledge lives in history, not in code. |
| 10 | Scripts | One stdlib CLI `okf.py`, one verb per deterministic job | Models do judgment; anything checkable is a script. |
| 11 | YAML | Strict frontmatter subset, own stdlib parser; anything outside it is a `validate` error | Zero dependencies, instant hooks, avoids PyYAML's timestamp coercion. |
| 12 | Models | Agents declare `model: haiku`/`sonnet` — a deliberate exception to the model-agnostic rule (PR #34) | Cheap background models are the product. Recorded in the adding-a-module skill. |
| 13 | pi activation | Dotfiles bridge activates `delegate_agent` when cwd has `.wiki/` | Today it activates only on a user-typed skill tag, so unprompted dispatch is dead on pi. |
| 14 | `log.md` | Not written; `git log -- .wiki/` is the changelog | Every PR prepending to one file guarantees merge conflicts. OKF makes it optional. |
| 15 | Self-improvement | `reflect`: agent-transcripts + git evidence → scorecard → content fixes auto-applied, prompt fixes as PR proposals | Transcripts are the only place rediscovery is visible; a self-editing fleet-wide prompt is too high-blast. |
| 16 | Replay eval | v1.1 | Needs real rediscovery cases to build its question set from. |
| 17 | Fan-out | Parallel subagents, default 4, set per call (`--fanout N`) or per machine (`OKF_WIKI_FANOUT`) | Width is a property of the machine's model capacity (local LLM slots, rate limits), not of the repo, so it is not committed config. |

## Module layout

```
modules/okf-wiki/
  package.json  .claude-plugin/plugin.json  cordis.patch.yml (empty)  plugin.json (generated)
  skills/
    wiki/SKILL.md          # the contract: format, types, capture bar, templates, receipts
    wiki/okf.py            # the one script; hooks and skills both call it
    wiki/references/       # type templates, anchor syntax, frontmatter subset
    capture/SKILL.md       # manual upsert → briefs scribe
    recall/SKILL.md        # context: fork → recall agent
    ingest/SKILL.md        # history-mined bootstrap → explorers → scribe
    tend/SKILL.md          # bundle-wide freshness + conformance report, offers heal
    reflect/SKILL.md       # effectiveness scorecard + fixes
  agents/
    scribe.md    model: haiku   # upsert concept via okf.py; never index.md
    recall.md    model: haiku   # read, run fresh, cited answer ≤ ~1.5k chars; read-only
    explorer.md  model: sonnet  # one history slice → proposed briefs; read-only
    auditor.md   model: sonnet  # judges sampled transcript excerpts for reflect; read-only
  hooks/hooks.json              # SessionStart + Stop → okf.py
  tests/
```

Skills call the script skill-relative (`./okf.py`, sibling skills `../wiki/okf.py`, per the
agent-transcripts precedent); `hooks.json` calls `${CLAUDE_PLUGIN_ROOT}/skills/wiki/okf.py`.
Agents receive the resolved script path in their brief from the main agent.

| Unit | Decides | Writes |
|---|---|---|
| Main agent | what is worth capturing; when to recall/heal/reflect | nothing in `.wiki/`; prints receipts |
| `scribe` | wording, merge vs new | concept files only |
| `recall` | which concepts answer; STALE flags | nothing |
| `explorer` | candidate concepts from one history slice | nothing |
| `auditor` | whether wiki use helped in a transcript excerpt | nothing |
| `okf.py` | nothing (deterministic) | `index.md`; state outside the repo |

## Data model

- Bundle: `.wiki/index.md` (generated; root frontmatter only `okf_version: "0.2"`) and
  `.wiki/<slug>.md`, slug `[a-z0-9][a-z0-9-]*`. No `log.md`. No state files in the repo.
  A type moves into its own subdirectory (`.wiki/gotchas/`) at 15 concepts via `okf.py mv`.
- Frontmatter, fixed key order, unknown keys preserved:

```yaml
---
type: gotcha
title: pnpm drops peer deps of workspace-linked modules
description: Linked modules lose peer deps under pnpm; add them to the root package.json, because hoisting skips links.
tags: [pnpm, deps]
generated: {by: okf-wiki/haiku, at: 2026-09-25T16:40:00Z}
verified:
  - {by: okf-wiki/haiku, at: 2026-09-25T16:40:00Z, commit: 527c417}
sources:
  - {id: s1, resource: "commit:e4132f6", title: fix peer deps}
---
```

- `description`: one sentence, claim + reason, ≤200 chars (validated) — it is the retrieval
  signal. `status: deprecated` hides a concept from the digest.
- `generated`/`verified` are written only by `okf.py stamp`; `commit` is `HEAD` at
  verification. Actor `okf-wiki/<alias>`; `human:<id>` only on explicit user confirmation.
- Body templates (from `okf.py new`), each ending with `## Verify`; ≤~400 words (warned):

| Type | Sections |
|---|---|
| gotcha | Symptom · What fails · What works · Why |
| decision | Decision · Why · Rejected alternatives · Revisit when |
| runbook | When · Steps · Check it worked |
| convention | Rule · Why · Example |
| architecture | Shape · Why this way · Boundaries |

- Claims cite `[^s1]` footnotes joined to `sources[].id`. Links are relative (`./other.md`)
  with relation-bearing link text.
- `## Verify` anchors are grep-only, never executed:

```
- `pkg/foo.py` :: `resolve_peers`        # file contains the symbol
- `pnpm-workspace.yaml` :: /hoist/ => 0  # regex match count equals N
- none: external vendor behavior         # UNANCHORED; allowed, tend lists it
```

- `index.md`: `# <Type>` sections of `* [Title](./slug.md) - description`. The digest is the
  same list capped at ~2k tokens (titles only beyond), STALE marked ⚠, deprecated and
  invalid concepts omitted, headed `okf-wiki:digest v<N>` where N is the prompt-set version.

## `okf.py` verbs

Stdlib only; the final stdout line is a stable status line (pr-flow convention).

| Verb | Job |
|---|---|
| `validate [ids]` | Frontmatter parses (subset), `type` in closed set, reserved-file shape, ISO timestamps with offset, `verified`/`sources` shape, footnote ids resolve, `## Verify` present, id regex, description length, relative links resolve (warn), secret patterns (error) |
| `index` | Rebuild `index.md` from concept frontmatter, ignoring the old file; write only when bytes change |
| `digest` | The budgeted SessionStart text |
| `new <type> <slug>` | Scaffold from template; reject bad slugs; report near-duplicates by title/tag overlap |
| `stamp <id> --by <actor> [--verified]` | Write `generated`/`verified` with real UTC time and `HEAD`, preserving key order and unknown keys |
| `fresh [ids]` | FRESH / STALE / UNANCHORED: STALE when `git log <commit>..HEAD` or `git diff HEAD` touches an anchor file; one batched git call for the whole bundle |
| `anchor <id>` | Evaluate grep anchors: confirmed / broken |
| `mv <old> <new>` | Rename a concept and rewrite every inbound link |
| `migrate <path>` | Mechanical conversion of an llm-wiki/OKF bundle: type case, anchor syntax, placeholder actors, key order |
| `gate` | Stop-hook state machine (below) |
| `stats` | Deterministic half of the `reflect` scorecard (below) |
| `fanout [--fanout N]` | Resolve the fan-out width: flag, else `OKF_WIKI_FANOUT`, else 4; error outside 1-16 |

## Flows

1. **Read (every session).** SessionStart hook → `git rev-parse --show-toplevel`; no `.wiki/`
   → silent exit. Else `index`, `validate` (one loud line on errors), `digest`; inject digest
   plus the rule "consult before non-trivial work; capture durable non-obvious findings",
   wrapped as reference data, not instructions. When the digest is not enough, main
   dispatches `recall` with the question; it reads concepts, runs `fresh`, returns a cited
   answer with `concept:<id>` citations, `STALE: <id>` flags and `GAP:` when unanswered.
2. **Capture.** Trigger: injected rule or Stop nudge. Main applies the capture bar and briefs
   `scribe` (type, claim, why, evidence, suggested anchor), in the background where
   supported. Scribe: `new` (or edit the flagged duplicate) → fill template → `anchor` until
   confirmed → `stamp` → `validate` → returns `created|updated <id>` or `rejected: <reason>`.
   Main prints `wiki: +<type>/<id>`. Writes land on the current branch, so knowledge ships in
   the PR that taught it.
3. **Heal.** `STALE` from recall or ⚠ in the digest → main dispatches scribe "re-verify
   <id>": still true → `anchor` + `stamp`; changed → edit + `stamp`; obsolete →
   `status: deprecated` with reason. Receipt `wiki: ~healed/<id>`.
4. **Ingest (on request).** Main slices sources (fix/revert commits by date window, PR
   bodies, docs/CLAUDE.md gotcha sections, existing bundles via `migrate`) → up to `fanout` parallel
   `explorer` agents → proposed briefs → main dedupes and applies the capture bar → scribe
   lands each → one summary receipt.
5. **Tend (on request).** `validate` + `fresh` over the bundle, orphans, near-duplicates →
   report + offer one batched heal. Never changes anything unasked.
6. **Reflect** — see Self-improvement.

## Hooks

```json
{"hooks": {
  "SessionStart": [{"hooks": [{"type": "command", "timeout": 5,
    "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/skills/wiki/okf.py\" hook-session-start"}]}],
  "Stop": [{"hooks": [{"type": "command", "timeout": 5,
    "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/skills/wiki/okf.py\" hook-stop"}]}]
}}
```

- Budget: <50 ms with no `.wiki/` (hooks run in every repo on the fleet); <500 ms at 250
  concepts. Both tested.
- Never block work: internal failures exit 0 with one stderr line
  `okf-wiki: <what> — <fix>`. Exit 2 is never used.
- Stop (`gate`): no-op when `stop_hook_active` or when the child-session env marker is set;
  otherwise block once with the nudge when `HEAD` moved since the last nudge, or the tree
  first became dirty this session (untracked files included). State lives at
  `$XDG_STATE_HOME/okf-wiki/<repo-hash>/<session_id>`, pruned after 7 days — never in the
  repo, never shared across sessions.

## Error handling

| Situation | Surface |
|---|---|
| `.wiki/` with zero concepts | digest says "empty wiki — run ingest" |
| `validate` errors | one injected line naming files; the concept is excluded from the digest until fixed |
| `validate` warnings | count in the digest header; full list in `tend` |
| scribe rejects or fails | main prints `wiki: ✗ <id> — <reason>` |
| agent dispatch unavailable | main does the work inline per the skill; receipt says `(inline)` |
| `python3` missing | the hook runner's fail-open line; skills still work by hand |
| merge conflict in a concept | frontmatter fails `validate`, concept leaves the digest until fixed; `index.md` heals itself because it is rebuilt from concepts |

Secrets: `validate` errors on AWS/GCP/GitHub/OpenAI/Slack key shapes, PEM blocks and
`password|token|secret` assignments — regex only, no entropy scoring (llm-wiki's misfired
on URLs, paths, camelCase). A concept with a secret error is never stamped or injected.
Nothing in a concept is ever executed; injected content is wrapped as data.

## Self-improvement: `reflect`

Evidence is the agent-transcripts index plus git; no new telemetry store.

1. **Traces.** Stable markers every wiki action already emits: `okf-wiki:digest v<N>`,
   `concept:<id>` / `GAP:` in recall answers, `wiki: +|~|✗` receipts.
2. **Scorecard.** `okf.py stats` computes the countable half from `transcript-query` output
   and git; `auditor` agents judge sampled excerpts for the rest.

| Question | Signal | A failure points at |
|---|---|---|
| Consulted? | digest-injected non-trivial sessions that recalled or read `.wiki/` | injected rule, skill descriptions |
| Hit? | cited answers vs `GAP:` | content gaps, capture bar |
| Helped? | auditor: did the cited concept change the next actions | description quality |
| Rediscovery | agent re-derived what an existing concept said | digest, descriptions, consult prompting |
| Right? | user corrections contradicting a concept; heal outcomes changed/obsolete | anchors, capture accuracy |
| Capture precision | concepts reverted/deprecated ≤30 days, or never retrieved in 60 | capture bar |
| Capture recall | fix commits with no capture after a nudge | nudge, capture rule |
| Cost | digest tokens, recall latency, calls per session | budgets |

3. **Act.** Wiki content fixes (prune unused, rewrite missing descriptions, merge duplicates,
   add missing concepts) are applied like captures, with receipts. Prompt/module fixes
   (injected rule, digest format, skill/agent text, capture bar) become a written proposal
   with evidence, opened as a marketplace PR for the user to approve. The loop never edits
   its installed module.
4. **Cadence.** The digest header shows `reflect due` after 20 sessions or 14 days since the last run; running it
   is the user's call.
5. **v1.1: replay eval.** A question set built from recorded rediscovery/miss cases, run with
   and without the wiki and with old vs new prompts, gates prompt proposals.

`reflect` needs the transcript index: agent-transcripts is off on Claude in the fleet today
(`modules.tsv`), so it runs from pi/dsh or the row is switched on.

## Fan-out

Every skill that has independent units of work dispatches them as parallel subagents, at
most `fanout` in flight, then merges in the main agent.

- **Width:** `--fanout N` on the skill invocation, else `OKF_WIKI_FANOUT`, else 4. `okf.py`
  resolves it (`okf.py fanout [--fanout N]`, validated 1-16) so every skill reads it the
  same way; an invalid value is an error, never silently clamped.
- **Where:** `ingest` (one `explorer` per history slice), `tend` heal batch and multi-finding
  `capture` (one `scribe` per concept), `reflect` (one `auditor` per excerpt sample).
  `recall` stays single: one forked agent reads a handful of concepts, and splitting it
  would add a merge step for no gain at v1 bundle sizes.
- **Safety:** main assigns each parallel scribe a disjoint set of concept ids, so no two
  write the same file; `index.md` is rebuilt by the hook afterwards, so parallel writers
  never touch it. More units than `fanout` → dispatched in waves.
- **Harness caps win:** pi's bridge runs at most 4 children in flight and queues the rest;
  Claude and dsh use the provider's limits. The effective width is `min(fanout, cap)`, and
  a receipt reports it when capped (`wiki: fanout 8 → 4 (pi cap)`).

## Harness fidelity

| Capability | Claude | pi | dsh |
|---|---|---|---|
| SessionStart digest | system context | `nextTurn` custom message (may be lost to compaction) | persistent `systemPrompt.context` |
| Stop nudge | blocks once per gate | once per session, as a user message (runner latch) | `agent.steer`; on the turn's critical path |
| Agent dispatch | native | after bridge activation on `.wiki/` | native |
| Background scribe | yes | no — foreground | if the provider supports continuation (to verify) |
| Cheap models | native aliases | alias → local fast/large models | inherits parent until `modelRoutes` configured |
| Fan-out width | `fanout` | `min(fanout, 4)` | `fanout`, provider limits |

## Paired dotfiles changes (land first)

1. pi `module-agents`: activate `delegate_agent` when cwd contains `.wiki/` (case 6).
2. dsh hook runner: set a child-session env marker so hooks can skip subagents (case 6).
3. dsh `modelRoutes` for `haiku` and `sonnet`.
4. `modules.tsv` row for `okf-wiki` (case 1).
5. After homelab migration: disable `llm-wiki` in the fleet (double registration, like case 3).

## Repo docs touched

- `.agents/skills/adding-a-module/SKILL.md`: record the okf-wiki model-alias exception.
- `agent-contract/README.md:71`: dsh background row is stale.
- `docs/planning/wiki/README.md`: point at this spec as superseding `decisions.md`.

## Testing

- `okf.py` unit tests per verb; the subset parser gets an accept/reject table; `index` output
  byte-stable across runs.
- Fixtures: upstream `acme_retail`; a hand-built bundle covering every type, anchor form,
  stale/deprecated/secret/broken case; a scrubbed homelab slice for `migrate` (private-path
  gate).
- Freshness in temp git repos: anchor-touching commit, rebase, uncommitted edit, missing
  anchor file.
- Hooks: time budgets, silence without `.wiki/`, gate states (dirty, commit, repeat,
  `stop_hook_active`, child marker), fail-open.
- Cross-harness smoke (`tests/smoke/`): digest delivered and Stop nudge delivered per harness.
- Manual value check at rollout: ~10 questions over the migrated homelab bundle, with vs
  without the wiki.

## Rollout

1. Dotfiles PR (bridge activation, child marker, model routes).
2. Marketplace PR: `okf-wiki` 0.1.0 + this spec.
3. Pin and enable in `modules.tsv`.
4. `ingest` with migration on homelab → first real `.wiki/` and the value check.
5. Retire `llm-wiki`.

## To verify during planning

- dsh `spawn` provider: does `run_in_background` continue or fall back to foreground?
- pi hook runner: does `session_start` awaiting a child process risk the known deadlock?
- The child-session marker mechanism on each harness (Claude: is `agent_id`/equivalent on
  Stop stdin sufficient?).
- Whether `transcript-query` exposes enough (message text search, session cwd) for `stats`.
- Whether a skill invocation argument (`--fanout N`) reaches the skill body identically on all
  three harnesses (`$ARGUMENTS` handling).

## Out of scope (v1)

Global bundle; code-scan ingest; UserPromptSubmit per-prompt ranking; embeddings; secret
blocking beyond `validate`; `log.md`; auto-merging prompt changes; the replay eval (v1.1);
a graph viewer; Attested Computation production (consumed as an ordinary `type`).

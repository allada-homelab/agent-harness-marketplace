# OKF v0.2 — what it is, distilled for the `wiki` module

Source of truth: `okf-upstream/SPEC.md` (vendored verbatim from
GoogleCloudPlatform/open-knowledge-format @ `ad30107`, 2026-08-21, Apache-2.0).
This file is the working summary; when they disagree, the spec wins.

## One-paragraph version

OKF is a directory of markdown files with YAML frontmatter. Every non-reserved
`.md` file is a **concept**; its **concept ID** is its bundle-relative path
minus `.md`. The only required frontmatter key is `type`. Two filenames are
reserved at every directory level: `index.md` (listing for progressive
disclosure) and `log.md` (newest-first change history). Relationships are
plain markdown links between concepts. v0.2 adds optional, first-class
frontmatter for **provenance** (`sources`), **trust** (`generated`,
`verified`), **lifecycle** (`status`, `stale_after`) and a new concept type,
**Attested Computation**. Consumers must be permissive: unknown types, unknown
keys, missing optional fields, broken links and missing indexes are never
errors.

## Bundle layout (§3)

```
<bundle>/
  index.md          # optional; root copy MAY carry frontmatter `okf_version: "0.2"` (only key allowed)
  log.md            # optional; newest-first, `## YYYY-MM-DD` headings
  <concept>.md
  <subdir>/
    index.md
    <concept>.md
```

- Distribute as a git repo (recommended), a tarball, or a subdirectory of a
  larger repo. The last is exactly our case: a wiki living inside a code repo.
- `references/` is a *convention*, not a requirement: a place to mirror
  external material, executor run-instructions, and attester code.
- No tag files. Tag browsing is synthesised by the consumer from frontmatter.

## Concept frontmatter (§4, §5)

| Key | Req | Shape | Notes |
|---|---|---|---|
| `type` | **yes** | string | Free vocabulary; consumers tolerate unknown values. |
| `title` | rec | string | Fallback: derive from filename. |
| `description` | rec | one sentence | Used verbatim in `index.md` bullets. |
| `resource` | rec | URI | The asset the concept describes. Absent for abstract ideas. |
| `tags` | rec | list of strings | |
| `generated` | opt | `{ by, at }` | `by` required inside it (actor). `at` = last meaningful content change. |
| `verified` | opt | list of `{ by, at }` or one bare mapping | Bare mapping MUST be read as one-element list. |
| `status` | opt | `draft` / `stable` / `deprecated` | Absent ⇒ `stable`. |
| `stale_after` | opt | ISO 8601 datetime w/ offset | Stale when `now >= stale_after`. Absolute, never a TTL. |
| `sources` | opt | list of entries | See below. |
| `usage_window` | opt | `{ from, to }` | Sibling of `sources`; frames every `usage_count`. |
| *anything else* | opt | — | Preserve on round-trip; never reject. |

Every timestamp is an ISO 8601 datetime **with an explicit UTC offset**
(`2026-06-30T14:00:00Z`). Date-only values are not valid timestamps.

### `sources[]` entries (§5.1)

- `resource` — required. An absolute URL, a bundle-relative path, a relative
  path, **or a scope descriptor** (free text like `all queries in project X`).
- `id` — optional but SHOULD be present when the body cites it. Footnote
  labels `[^id]` in the body join to `sources[].id`. Keyed, not positional,
  because agents reorder lists.
- `title` — optional label.
- Credibility signals, all optional: `author` (actor), `usage_count` (int over
  `usage_window`), `last_modified` (datetime). OKF records the *signals*, never
  a score.
- Lineage = links. A `resource` pointing at another concept is already a graph
  edge; consumers MAY recurse into that concept's own `sources`.

### Actor convention (§7)

- `<producer>/<version>` for agents/tools, e.g. `reference_agent/gemini-2.5-pro`
- `human:<id>` for people — **this prefix is what trust tiers key off**
- `process:<id>` for automated processes

### Trust tiers (§5.3), derived not stored

| `verified` state | tier |
|---|---|
| absent | unverified |
| only non-`human:` actors | machine-confirmed |
| any `human:` actor | human-reviewed |

Advisory only; not access control.

## Body (§4.2)

Free markdown. Structural markdown preferred over prose. Conventional
headings: `# Schema`, `# Examples`, `# Computation`. No `# Citations` section
(that was v0.1; provenance moved to `sources`). Per-claim attribution is a
footnote keyed to a source id.

## Links (§6)

- Bundle-absolute `/tables/x.md` is the spec's *recommended* form.
- Relative `../tables/x.md` is also valid. **Note:** the upstream reference
  agent's own prompt forbids leading-`/` links "because that breaks GitHub
  rendering" and uses relative paths everywhere. The spec and the reference
  implementation disagree here; we should pick one and state it (see
  `reference-implementations.md`).
- Links are untyped directed edges; the relationship kind lives in prose.
- Broken links are legal (not-yet-written knowledge).

## `index.md` (§8)

- No frontmatter, except the root index MAY carry `okf_version: "0.2"`.
- One or more `# Section` headings, each a bullet list:
  `* [Title](relative-url) - description`. Subdirectories listed as
  `[name](subdir/)` or `[name](subdir/index.md)`.
- May be generated; consumers may synthesise one when absent.

## `log.md` (§9)

- `# <Title>` then `## YYYY-MM-DD` headings, newest first.
- Bullets with a conventional bold verb: `**Update**`, `**Creation**`,
  `**Deprecation**`, `**Initialization**`. Convention only.
- Spec says nothing about frontmatter on `log.md`. The upstream acme_retail
  sample puts `type: Log` frontmatter on it, which the spec's conformance text
  (§11.1 "every non-reserved .md file") neither requires nor forbids. Treat as
  allowed-but-unnecessary; we should not emit it.

## Attested Computation (§10) — the part we probably skip in v1

A concept of `type: Attested Computation` carries a sanctioned way to compute a
value: `runtime` (required), `parameters` (`{name, type, required}` list),
`computation` (path, or inline `# Computation` fence), `executor`
(`{resource, receipt: [...]}`) and `attester` (`{resource}` — deterministic,
no-LLM code that checks a receipt). Receipts and verdicts are runtime
artifacts, not stored in the bundle. Designed for data-warehouse metrics.
For a code-repo wiki this maps loosely onto "a command whose output proves a
claim" but the spec explicitly defers the runtime protocol, ABI and sandboxing
to a future version. Recommendation: consume it gracefully (it's just another
`type`), do not produce it in v1.

## Conformance (§11) — what a validator may and may not enforce

MUST-level, the whole list:

1. Every non-reserved `.md` has parseable YAML frontmatter.
2. Every frontmatter has non-empty `type`.
3. `index.md` / `log.md` follow §8 / §9 when present.
4. Bare `verified` mapping is read as a one-element list.
5. Never reject for a missing optional family.

MUST NOT reject for: missing optional fields, unknown `type`, unknown keys,
broken links, missing `index.md`. Everything else is SHOULD.

## v0.1 → v0.2 (§13)

Breaking: `timestamp` ⇒ `generated.at`; body `# Citations` ⇒ `sources`.
Consumers MAY fall back to both legacy forms. Everything else additive.

## What this implies for the `wiki` module

Things the spec settles for us, so we don't re-decide them:

- Storage is a directory of markdown in the repo. No DB, no server.
- The validator is tiny: frontmatter parses, `type` non-empty, reserved files
  well-formed. Everything else is a warning at most.
- Freshness is `stale_after` + `verified[].at`, compared against now. No TTLs.
- Agents write with `generated.by: wiki/<model>`; a human sign-off is the
  *only* way to reach the human-reviewed tier, so the skill must never write
  `human:` on the user's behalf without an explicit confirmation.
- Provenance for a code-repo wiki is `sources[].resource` = a repo-relative
  file path (or `path:line`), a commit SHA, a URL, or a scope descriptor like
  `git log -- src/auth/`. All four are legal `resource` values.

Things the spec leaves to us (planning decisions, not yet made):

- Bundle location inside a repo (e.g. `wiki/`, `.wiki/`, `docs/wiki/`).
- The `type` vocabulary for code knowledge (Decision, Gotcha, Runbook,
  Convention, Module, ...).
- Link style: bundle-absolute (spec-recommended) vs relative (upstream agent,
  GitHub-renderable).
- Whether `index.md` is regenerated deterministically by the skill or written
  by the model.
- How "update in real time" is triggered across three harnesses with no
  executable code allowed in this repo (skills only).

# Reference implementations in GoogleCloudPlatform/open-knowledge-format

Reviewed at commit `ad30107` (2026-08-21). The repo is young: first real
commit 2026-08-14, six commits total, one merged PR (ISO datetimes). It ships
the spec plus **one** producer, **one** consumer, **one** connector, and four
sample bundles. Everything is Apache-2.0.

## Inventory

| Piece | Where | Lines | What it is |
|---|---|---|---|
| Spec | `SPEC.md` | 1006 | The format. Vendored to `okf-upstream/SPEC.md`. |
| Reference agent (producer) | `src/reference_agent/` | ~2 400 py | Google ADK + Gemini agent that reads BigQuery metadata and crawls seed URLs, writing one OKF doc per table/dataset. |
| Bundle library | `src/reference_agent/bundle/` | ~380 py | Frontmatter parse/serialize, concept-id ↔ path, `index.md` regeneration, trust-tier / staleness helpers. |
| Agent tools | `src/reference_agent/tools/bundle_tools.py` | 205 py | `read_existing_doc` / `write_concept_doc` with write guards. |
| Prompts | `src/reference_agent/prompts/*.md` | 106 + 269 | The producer's system prompts. Vendored to `okf-upstream/prompt-*.md`. |
| Visualizer (consumer) | `src/reference_agent/viewer/` | 222 py + js/css | `visualize` subcommand: bundle → single-file Cytoscape graph HTML. |
| Connector | `connectors/gcp-knowledge-catalog.md` | doc only | Push/pull a bundle to GCP Knowledge Catalog via an external `kcmd` CLI. |
| Sample bundles | `bundles/{ga4,stackoverflow,crypto_bitcoin,acme_retail}` | md | Generated output. Only `acme_retail` exercises the v0.2 trust/attestation families. Vendored to `okf-upstream/sample-bundle-acme_retail/`. |
| Tests | `tests/` | ~900 py | pytest over document, index, tools, viewer, fetcher. |

Dependencies of the Python package: `google-adk>=2.0`, `google-cloud-bigquery`,
`pyyaml`, `pydantic`, `markdownify`. Python ≥3.11. There is **no** PyPI
release; install is `pip install -e .` from a clone.

## Piece-by-piece: can we use it?

### `bundle/document.py` — YES, as the model for our rules (not as code)

147 lines. Things worth copying into the skill's instructions verbatim:

- Frontmatter is the block between the first line `---` and the next `---`
  line. Unterminated block ⇒ error. Non-mapping YAML ⇒ error.
- **Timestamps must round-trip as strings.** PyYAML (YAML 1.1) silently turns
  `2026-06-30T14:00:00Z` into a datetime and dumps it back as
  `2026-06-30 14:00:00+00:00`. They subclass `SafeLoader` to drop the timestamp
  resolver. Any tool we tell the model to use (or any future script) has the
  same trap; YAML 1.2 parsers don't.
- `normalize_verified()` — bare mapping ⇒ one-element list.
- `trust_tier()` — the three-tier derivation, ~10 lines.
- `is_stale()` — **ignores** a `stale_after` without a `T` or without a tz
  offset rather than guessing. Good defensive rule to adopt.

### `bundle/index.py` — YES, as the algorithm for `index.md` regeneration

117 lines, fully deterministic except one optional LLM call:

1. Collect every directory that contains an `.md` anywhere beneath it.
2. Process deepest-first.
3. For each directory: one bullet per `.md` (title from frontmatter or stem,
   description from frontmatter), grouped under `# <type>` headings sorted
   alphabetically, entries sorted case-insensitively by title; one bullet per
   subdirectory under a `# Subdirectories` heading linking `sub/index.md`.
4. A subdirectory's description is its single child's description if it has
   exactly one child, else an LLM-written one-liner (with a non-LLM fallback:
   `Contains N entries: a, b, c.`).

Takeaway for us: the listing itself needs no model. Only the subdirectory
one-liner does, and the fallback is acceptable. This is a strong argument for
making `index.md` **regenerated, never hand-edited** in our skill, exactly as
this repo treats `modules/index.yaml`.

### `bundle/paths.py` — YES, adopt the ID rule

Concept-id segments match `[A-Za-z0-9_][A-Za-z0-9_.\-]*`. Path =
`bundle_root/<segments...>.md`. Simple; adopt as-is.

### `tools/bundle_tools.py` — PARTIALLY, the *guards* are the valuable part

The two tool functions are ADK-specific, but the behaviours are portable
skill rules:

- `write_concept_doc` is a **full replacement, not a patch**: the caller must
  send every existing key. The prompt spends a whole section hammering this
  ("omitting a key drops it"). For us: tell the model to read-then-write the
  whole file, or give it an edit discipline that preserves frontmatter.
- `generated` is **stamped by the tool**, not written by the model:
  `{by: reference_agent/<model>, at: now}` if absent. With no executable code
  in our module, the model has to stamp it itself; the skill must say so and
  name the actor string.
- Preferred frontmatter key order: `type, resource, title, description, tags,
  status, generated, verified, stale_after, sources, usage_window`, then
  unknown keys in original order. Adopt for stable diffs.
- **Augmentation guard**: during enrichment, refuse a write that shrinks an
  existing `# Schema` field set or the `sources` list. Generalises to "an
  update may not drop sources or shorten a schema-like section". Worth a rule.
- `validate()` refuses to write a doc with empty `type`.

### Prompts — YES, the best starting material in the repo

`reference_instruction.md` (one concept per invocation, read-existing →
gather → list-concepts-for-links → write once) and
`web_ingestion_instruction.md` (crawl seeds, per page: enrich / mint
`references/<slug>` / skip) are battle-tested OKF-producing prompts. Their
"mint a new reference" test is directly reusable for "should this finding be
its own concept": topic shape, not meta, citation test ("can I write *See the
[X] for…*"), reuse test (≥2 concepts benefit). Also reusable: cross-link
rules (only link to ids that exist, one link per mention per section, never
link from headings/code/schema), and "do not invent fields, URLs, or link
targets".

Caveat: both prompts are written for BigQuery tables and web pages, and they
**mandate relative links and forbid leading `/`**, contradicting the spec's
recommendation. That's the one design fork they force on us.

### Viewer — NO for v1, maybe later as an external tool

Good idea (bundle → self-contained HTML graph with backlinks, search, type
filter), but it's Python + CDN JS and we ship skills only. The useful bit is
its **link extraction** regex approach: collect `[...](target)` from bodies,
resolve relative to the doc's directory, keep only targets inside the bundle.
If we ever want a graph view, generating one from Claude Code as a one-off
artifact is more our shape than shipping the generator.

### Reference agent runner / ADK / BigQuery source — NO

Google ADK + Gemini + BigQuery. Wrong stack, wrong domain (data catalog, not
code repos), and this repo forbids `lib/`/`extensions/`. Nothing to reuse
beyond the prompts and the bundle library's rules above.

### Connector (GCP Knowledge Catalog) — NO

Documentation for pushing a bundle into Dataplex via a separate `kcmd` tool
from another repo. Irrelevant to a repo-local wiki. Only interesting fact: it
round-trips just seven frontmatter keys, confirming which keys the ecosystem
treats as core: `type, title, description, tags, resource, generated, sources`.

### Sample bundles — YES, `acme_retail` as the v0.2 exemplar

It is the only bundle with `verified`, `status: deprecated`, `stale_after`,
full `sources` with credibility signals, an `Attested Computation`, an
executor `Skill`, and an attester script. The three auto-generated bundles
(`ga4`, `stackoverflow`, `crypto_bitcoin`) show what the producer actually
emits: block-style `tags`, `generated` as a nested mapping, `at` quoted with
`+00:00`, `sources` with `id`/`title`/`resource`. Useful as realistic output to
test a validator against. Vendored `acme_retail` minus its `viz.html`.

## Inconsistencies noticed upstream (so we don't re-litigate)

1. **Link form.** Spec §6.1 recommends bundle-absolute `/x.md`; the reference
   prompts forbid it and require relative paths for GitHub rendering. The
   generated bundles are all relative.
2. **`log.md` frontmatter.** `acme_retail/log.md` carries `type: Log`
   frontmatter; spec §8/§9 only permit frontmatter on the root `index.md`.
3. **Date-only `stale_after`.** Older text/sample may use `YYYY-MM-DD`; the
   2026-08-20 "ISO datetimes" PR made every timestamp a full datetime with
   offset, and `is_stale()` ignores date-only values.
4. **`generated.at` format drift.** Spec examples use `...Z`; the generated
   bundles use `'...+00:00'` (quoted, from Python `isoformat`). Both are valid
   ISO 8601 with offset; a validator must accept both.

## Bottom line

Nothing here is installable or shippable as part of a skills-only module, and
nothing here targets code repositories. What *is* reusable, and should be
lifted into the skill text and any future tiny helper:

- the parse/serialize rules and the YAML-timestamp trap,
- the deterministic `index.md` algorithm,
- the concept-id regex,
- the trust-tier and staleness derivations,
- the write guards (full-replace discipline, stamp `generated`, key order,
  never shrink sources),
- the "mint a new concept?" four-part test and the cross-link rules from
  the prompts,
- `acme_retail` as the conformance fixture.

The whole reusable surface is ~300 lines of Python and ~375 lines of prompt;
re-expressing it as skill instructions is smaller than depending on the repo.

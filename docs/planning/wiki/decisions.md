# wiki module — decisions

Concrete decisions for the module. One entry per question. A decision is made
when `Decision:` is filled in; until then the entry lists the options we know
about. Append new questions at the bottom, never delete a decided entry. If a
decision is reversed, add a new entry that supersedes it and link both ways.

Status legend: **OPEN** · **DECIDED** · **SUPERSEDED by D-nn**

---

## D-01 Bundle location inside a target repo

Status: OPEN

Where the OKF bundle root lives in a repo the module is used on.

Options:
- `wiki/` at repo root. Visible, renders on GitHub, obvious to humans.
- `.wiki/` at repo root. Hidden from casual browsing, signals "tooling-owned".
- `docs/wiki/`. Sits with existing docs; may collide with doc generators.
- Configurable with one default. Adds a config surface to every skill.

Decision: .wiki/

Why: My decision. Follows the .remember , .claude , etc format and makes sense.

---

## D-02 Bundle layout and concept-id scheme

Status: OPEN

Flat (every concept at the root) versus sectioned (subdirectories by type or
by area). Decides the shape of `index.md` and how concept ids look.

Options:
- Flat, slug filenames. Simplest; one `index.md`; ids are one segment.
- Sectioned by `type` (`decisions/`, `gotchas/`, `runbooks/`). Index per section.
- Sectioned by code area (mirrors the repo tree). Ids follow source paths.

Decision:

Why:

---

## D-03 `type` vocabulary for code knowledge

Status: OPEN

OKF leaves `type` free. Consumers must tolerate unknown values, so this is a
recommendation to the model, not a validator rule.

Candidate set: `Decision`, `Gotcha`, `Runbook`, `Convention`, `Module`,
`Reference`, `Architecture`, `Glossary`.

Decision:

Why:

---

## D-04 Link style

Status: OPEN

Spec §6.1 recommends bundle-absolute `/path/x.md`. The upstream producer
forbids leading `/` and emits relative links so files render on GitHub.

Options:
- Relative (`../gotchas/x.md`). Renders on GitHub and in editors; breaks on move.
- Bundle-absolute (`/gotchas/x.md`). Move-stable; does not render on GitHub.

Decision:

Why:

---

## D-05 Command surface

Status: OPEN

Which skills exist and what each is named. The user-stated verbs are create,
generate, recall, add to, update in real time.

Candidate skills:
- `wiki-init` — create an empty conformant bundle.
- `wiki-ingest` — bootstrap concepts from a repo.
- `wiki-capture` — add or update one concept from a finding.
- `wiki-query` — answer a question with cited concepts, read-only.
- `wiki-index` — regenerate every `index.md` deterministically.
- `wiki-tend` — report stale, unverified, orphaned, or broken-link concepts.

Decision:

Why:

---

## D-06 "Real time" updates without executable code

Status: OPEN

This repo ships skills only: no hooks, no scripts. How does the wiki get
updated as work happens?

Options:
- Skill-only: a skill the model is instructed to invoke when it learns
  something durable. Works on all three harnesses; relies on the model.
- Harness-side hook outside this module (maintainer dotfiles layer) that
  nudges or invokes the capture skill. Reliable; not portable via this repo.
- Both: skill is the contract, hook is an optional accelerator.

Decision:

Why:

---

## D-07 `index.md` generation

Status: OPEN

Options:
- Regenerated deterministically from frontmatter, never hand-edited (same
  policy as this repo's `modules/index.yaml`). Subdirectory one-liners from the
  model or a fixed fallback.
- Model-written and hand-editable.

Decision:

Why:

---

## D-08 Write discipline and frontmatter rules

Status: OPEN

Rules the capture skill must follow on every write. Upstream's guards are the
starting point.

Candidate rules:
- Read the whole file, then write the whole file; never drop an existing key.
- Stamp `generated: { by: wiki/<model>, at: <now UTC> }` on every content change.
- Key order: `type, resource, title, description, tags, status, generated,
  verified, stale_after, sources, usage_window`, then unknown keys.
- Never shrink `sources`; never remove a schema-like section's entries.
- Never write a `human:` verifier without an explicit user confirmation.
- Timestamps are full ISO 8601 datetimes with offset; never date-only.

Decision:

Why:

---

## D-09 Provenance for code knowledge

Status: OPEN

What goes in `sources[].resource` for a finding about a repo.

Options, all legal under §5.1:
- Repo-relative path, optionally `path:line`.
- Commit SHA or `path@sha`.
- A URL (issue, PR, external doc).
- A scope descriptor in prose (`git log -- src/auth/`).

Decision:

Why:

---

## D-10 Attested Computation support

Status: OPEN

Options:
- Consume only: treat as an ordinary `type`, never produce it.
- Produce a code-repo flavour (a command whose output proves a claim).
- Ignore entirely.

Decision:

Why:

---

## D-11 Validation and fixtures

Status: OPEN

How the module proves its output is conformant with no executable code.

Options:
- A checked-in fixture bundle under the module's tests, validated by this
  repo's existing test harness.
- Skill-text-only rules, no automated check.

Decision:

Why:

---

## D-12 Module name and skill prefix

Status: OPEN

Module directory is `modules/wiki`. Skill names need a prefix that won't
collide with other marketplace modules or harness built-ins.

Decision:

Why:

---

## Template for new entries

```
## D-nn Short title

Status: OPEN

One or two sentences on the question.

Options:
- ...

Decision:

Why:
```

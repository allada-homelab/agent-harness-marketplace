---
name: wiki
description: The contract for this repo's agent wiki at .wiki/ (Open Knowledge Format v0.2) — what belongs in it, the six concept types and their templates, the frontmatter and Verify-anchor rules, the okf.py script that does every deterministic step, and the receipt lines. Read it before writing, moving or judging any .wiki/ file; the capture, recall, ingest, tend and reflect skills build on it.
---

# okf-wiki: the contract

`.wiki/` at the repository root is a small knowledge bundle for agents. Each concept is one
markdown file with YAML frontmatter. The point is knowledge the code cannot tell you: why a
thing is the way it is, what breaks and how, how to operate it. A good wiki makes the next
agent faster and keeps it from repeating a mistake.

## The capture bar

Write a concept only when **all** hold:

1. **Not recoverable by grepping the code.** File maps, signatures and restated docs fail.
2. **Durable.** It will still be true next month, or it records a decision with its reason.
3. **Actionable.** Its description can change what the next agent does.

Good: a runtime failure mode and its cause, a rejected alternative and why, a deploy step
that is easy to get wrong, a convention the linter cannot enforce, an external system's
quirk. Bad: "the auth module lives in src/auth", a summary of a README, a changelog entry.

## Types and templates

Exactly one of `gotcha`, `decision`, `runbook`, `convention`, `architecture`, `reference`.
Body sections per type (the script scaffolds them):

| Type | Sections |
|---|---|
| gotcha | Symptom · What fails · What works · Why |
| decision | Decision · Why · Rejected alternatives · Revisit when |
| runbook | When · Steps · Check it worked |
| convention | Rule · Why · Example |
| architecture | Shape · Why this way · Boundaries |
| reference | What · Where · Caveats |

Every concept ends with `## Verify`. Keep the body under about 400 words.

## Frontmatter

```yaml
---
type: gotcha
title: pnpm drops peer deps of workspace-linked modules
description: Linked modules lose peer deps under pnpm; add them to the root package.json, because hoisting skips links.
tags: [pnpm, deps]
generated: {by: okf-wiki/haiku, at: 2026-09-25T16:40:00Z}
verified:
  - {by: okf-wiki/haiku, at: 2026-09-25T16:40:00Z, commit: 527c417aa1b2}
sources:
  - {id: s1, resource: "commit:e4132f6", title: fix peer deps}
---
```

- `description` is the retrieval signal: one sentence, a claim plus its reason, at most 200
  characters. Agents often act on the description alone.
- **Never type `generated` or `verified` yourself.** `okf.py stamp` writes them with the real
  time and commit.
- `human:<id>` appears in `verified` only after the user explicitly confirmed the concept.
- Cite claims with footnotes `[^s1]` that match a `sources[].id`. A source is a repo path, a
  `commit:<sha>`, a full PR or issue URL, or a short description of where it came from.
- Link other concepts with relative links, `[<how it relates>](./<id>.md)`, and let the link
  text say how they relate ("the cache it depends on", not "see here").
- Never write credentials, tokens or keys, not even as examples. Use `<placeholder>`.
- To retire a concept, set `status: deprecated` and say why in the body.

## Verify anchors

Grep-only checks the script evaluates; nothing in a concept is ever executed.

```
- `pkg/foo.py` :: `resolve_peers`        # the file contains this literal text
- `pnpm-workspace.yaml` :: /hoist/ => 0  # the regex matches exactly N times
- none: external vendor behaviour         # no code anchor exists; say why
```

Anchor the files whose change would make the concept wrong. Paths are repo-relative. Never
use line numbers.

## okf.py

`./okf.py` beside this file (resolve it against this skill's directory, not the repo). Run it
with `python3` from anywhere inside the repository. The last line is always
`okf: <verb> <verdict> [detail]`; act on it.

| Verb | Use |
|---|---|
| `new <type> <slug> [--title T]` | scaffold a concept; exit 3 lists near-duplicates to update instead (`--force` only when they truly differ) |
| `stamp <id> --by okf-wiki/<model> [--generated] [--verified]` | after a content change pass both; after a re-check pass `--verified`; it refuses while anchors fail |
| `validate [ids]` | conformance; fix every ERROR |
| `anchor <id>` | evaluate the Verify anchors |
| `fresh [ids]` | FRESH / STALE / UNANCHORED / UNVERIFIED from git |
| `mv <old> <new>` | rename and rewrite every inbound link |
| `index`, `digest` | rebuild `index.md`, print the session digest (hooks do both) |
| `migrate <dir> [--dry-run]` | import another OKF or llm-wiki bundle |
| `fanout [--fanout N]` | parallel width: flag, else `OKF_WIKI_FANOUT`, else 4 |
| `stats [--mark]` | effectiveness counts for the reflect skill |

Never edit `.wiki/index.md` by hand; the hooks rebuild it. There is no `log.md`: history is
`git log -- .wiki/`.

## Receipts

After any wiki change, print exactly one line per concept so the user can see and revert it:

- `wiki: +<type>/<id>` created or updated
- `wiki: ~healed/<id>` re-verified or fixed after going stale
- `wiki: -deprecated/<id>` retired
- `wiki: ✗ <id> — <reason>` a write that failed or was rejected
- add ` (inline)` when you did the scribe's work yourself because no agent tool was available

## Dispatching the okf-wiki agents

The agents are `okf-wiki:scribe`, `okf-wiki:reader`, `okf-wiki:explorer` and
`okf-wiki:auditor`. On Claude Code use the Agent tool with that `subagent_type`, in the
background for the scribe. On pi and dsh use `delegate_agent` with that `agent_type`; on dsh
also pass `run_in_background: true` for the scribe. Every brief must include the absolute
path of `okf.py`. If no agent tool exists, follow the agent's steps yourself.

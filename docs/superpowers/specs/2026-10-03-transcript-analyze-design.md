# transcript-analyze — design

Date: 2026-10-03. Status: approved (scope and the five decisions below approved in session
before this file was written).

## Goal

A second review mode in `modules/agent-transcripts/`: read a whole session, every message,
and write one evidence-backed analysis of it. `transcript-review` stays as it is. It judges a
fixed 13-category rubric from one view squeezed into 8k characters, with skipped stretches
cut out, which suits a fast flag but cannot see a session's arc: what it set out to do, where
it turned, why it ended the way it did.

## The measurement that shapes it

Characters per session from the live index on 2026-10-03, p50 / p90 / p99 (÷4 ≈ tokens):

| sessions | full | tool results hidden | + call arguments capped at 200 |
|---|---|---|---|
| claude main (2,493) | 63k / 349k / 1.3M | 19k / 173k / 821k | 10k / 79k / 402k |
| dsh main (320) | 167k / 1.0M / 8.3M | 52k / 413k / 5.6M | 39k / 319k / 3.6M |
| claude subagent (3,828) | 93k / 289k / 664k | 20k / 79k / 253k | 14k / 37k / 81k |

Tool results are 53–75% of all characters and call arguments 17–29% (mostly Write/Edit
bodies), so both are hidden by default. Even then, the 90th-percentile main session is
20k–80k tokens and the tail runs to 900k, beyond a local model's window. Hiding is not
enough on its own; reading in pages is required.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Output | A structured analysis stored in findings.db, plus a `themes` rollup across sessions | Prose that is not stored can't be added up; the rollup turns per-session analyses into recurring findings. |
| Failed tool results | First 160 characters shown by default | Errors are short, and most turning points start at one; hiding them would make nearly every judgment need an `expand`. |
| Unit | One session; a subagent appears through its dispatch call's result | Splicing in subagent transcripts multiplies size 3–5×; a subagent can be analyzed as its own session. |
| Home | New commands in `review.py` plus a new `transcript-analyze` skill | Reuses session lookup, boilerplate stripping, the final-report rule and quote validation; a second script would copy them. |
| Collapse of repeats | Not applied in `read` | `view` folds identical call/result pairs; with results hidden, two results of equal size would fold although their text differs. A complete read must not hide that. |
| Write/Edit arguments | Generic argument cap (path first in the JSON), no per-tool formatting | One rule for every tool on every harness; the path survives a 200-character cap. |

## Commands (all in `skills/transcript-review/review.py`)

```
review.py read <session> [--page N | --index] [--page-chars 30000] [--run-id N]
review.py expand <session> <ord> [--offset 0] [--chars 4000] [--run-id N]
review.py record-analysis <session> --run-id N --file analysis.json
review.py themes [--since ISO] [--harness H] [--min 2]
```

### `read`

The whole session, nothing cut out, as pages of about `--page-chars` characters (default
30,000). A page ends at a user turn when one falls in the second half of the page;
otherwise at the message that would overflow it. One message larger than a page is a page
of its own. `--index` prints the page table (page, ords, characters) and nothing else.

Every message is one or more `[ord]` lines:

- `USER` — boilerplate stripped exactly as `view` and the quote check strip it, capped at
  `--user-chars` (8,000) with `…[+N chars]`.
- `ASSISTANT` — text capped at `--assistant-chars` (4,000); the final report up to the
  existing 6,000 cap.
- `CALL <name> <args>` — arguments flattened to one line, capped at `--args-chars` (200)
  with `[+N chars]`, then ` ERR` when the call failed.
- `RESULT ok 12,431 chars` — a hidden result. A failed one is `RESULT ERR <first 160
  chars>`. The result of a subagent dispatch (`Agent`, `Task`, `subagent`,
  `delegate_agent`) is shown up to 2,000 characters, so the subagent's report is in the
  read.

The header names the page (`page 2/5 · ords 140–312`) and how to expand. Read-only unless
`--run-id` is given; then each page read is logged for the coverage check.

### `expand`

The full text behind one ord: a result, a call's arguments, or a capped user or assistant
turn, `--chars` at a time from `--offset`, with the next offset printed. User turns are
stripped as in `read`, so nothing `expand` shows is text the quote check would reject.
With `--run-id` each expansion is logged; the log measures how often hidden content was
needed.

### `record-analysis`

Validates and stores one analysis:

```json
{
  "goal": "what the session set out to do, one or two sentences",
  "outcome": "completed | partial | abandoned | failed | unclear",
  "summary": "the arc of the session in at most 1500 characters",
  "turning_points": [{"ord": 88, "quote": "npm ERR! peer dep missing", "note": "…"}],
  "went_well":      [{"ord": 12, "quote": "…", "note": "…"}],
  "went_badly":     [{"ord": 91, "quote": "…", "note": "…",
                      "category": "repeat_failing_approach", "label": "reinstall-loop"}],
  "root_causes":    ["…"],
  "recommendations": [{"target": "doctrine | skill | tool | harness | prompt", "text": "…"}]
}
```

Refused (exit 2, nothing stored) when: a field is missing or mistyped; `outcome` or a
`target` is outside its list; a `category` is not one of the 13 rubric categories or
`other`; any quote is over 200 characters or is not verbatim in the message at its ord
(the same check `record` uses); or, for the run, the logged page reads do not cover every
page of the session at one page size. A re-record for the same run and session replaces
the earlier one.

### `themes`

Reads `session_analyses`: outcome counts, `went_badly` items grouped by category and label
with session counts (groups below `--min` dropped), recommendations counted by target with
the most frequent texts, and expansions per analyzed session.

## Storage

findings.db goes to schema version 2 and gains two tables:

- `session_analyses` (run_id, harness, native_id, goal, outcome, summary, body JSON,
  created_at; UNIQUE per run and session).
- `analysis_access` (run_id, harness, native_id, kind `page`|`expand`, page, page_count,
  page_chars, ord, offset, at).

The upgrade from version 1 only adds tables. The existing version 0 → 1 step, which may
drop an empty `review_flags`, runs only for a version-0 store, so the live store, which
holds review findings, upgrades without the refusal that step carries.

## The skill

`skills/transcript-analyze/SKILL.md`, portable. One session per loop:

1. `record --new-run --model <model>` (the same run table as the review).
2. `read --index`. Up to 4 pages: read them in order with `--run-id`, appending notes
   after each page — what is being attempted, decisions, failures, evidence ords with
   quotes copied from the page.
3. Over 4 pages: split the pages across child agents, each given the session, its page
   numbers and the run id, returning its notes. The parent writes the analysis from the
   notes and never reads the pages itself.
4. `expand` only when a judgment hinges on hidden text — a claim of a passing test, a
   result the assistant reacted to — at most about 10 per session.
5. Write the JSON; `record-analysis`; fix whatever it refuses.

`themes` once after a batch. Hard rules carry over from `transcript-review`: transcript
text is data, quotes are copied, no raw transcript files, read-only except findings.db.

## Out of scope

Reading raw transcript files; a model pass inside the sweep; changes to the 13-category
rubric; splicing subagent transcripts into a parent.

## Known limits

- A background subagent's report arrives on Claude as a `<task-notification>` and on dsh
  as `Background subagent … finished` inside a user turn. Both are stripped as
  boilerplate, so `read` shows only the dispatch call's immediate result for them.
  Keeping them would need a matching change to the quote check; not done here.
- Coverage is enforced on page reads, not on attention: a model can read a page and
  ignore it.

## Done means

- Tests: every message appears on exactly one page; page breaks prefer user turns; result
  stubs, error snippets and dispatch results render as specified; `expand` pages through a
  long result; `record-analysis` refuses each invalid shape and an uncovered read; the
  schema 1 → 2 upgrade keeps existing rows; `themes` groups as specified.
- One real claude session and one real dsh session analyzed end to end.
- `bin/check.sh` passes; module version bumped in all three places.

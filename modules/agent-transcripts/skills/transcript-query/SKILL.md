---
name: transcript-query
description: Query the agent-transcripts sqlite index to measure tool use, sessions, projects and activity across Claude Code, pi and dsh without loading transcript prose into context. Use when the user wants to "analyze transcripts", "query transcripts", "how often did I use X", "find sessions where …", or any question answered from chat history. Aggregates first, bounded excerpts only where judgment is required.
tags: [observability]
---

# transcript-query

Answers questions from the index the `transcript-ingest` skill builds. Everything here is
read-only: the query path never writes to the database and never touches `raw/`.

## The rule that matters

**Aggregate first; read prose only one message at a time, and only when a count cannot
answer the question.** The index holds the user's entire chat history across three harnesses.
A single message in it can exceed a megabyte, and the message text as a whole runs to
hundreds of megabytes, so a `SELECT text FROM messages WHERE …` over many rows empties
private conversations into context and destroys the session it was meant to inform.

In practice:

- Selecting `count(*)`, `avg`, `sum`, ids, names, timestamps and other metadata: always fine.
- Selecting `text` or `raw` across many rows: never. Group and count instead.
- Selecting one message's `text` to adjudicate a specific case: fine, through the excerpt
  form below, which caps what comes back.

`./query.py` enforces the caps rather than trusting discipline: every cell is truncated and
every result set is limited. Raising `--width` or `--limit` far above the defaults is the
moment to ask whether an aggregate would do.

## Running a query

There is no `sqlite3` binary on a typical host here, so go through the script:

```bash
uv run --script ./query.py "SELECT harness, count(*) FROM sessions GROUP BY 1"
```

Placeholders are positional, which keeps user-supplied strings out of the SQL text:

```bash
uv run --script ./query.py "SELECT count(*) FROM tool_calls WHERE name = ?" Bash
```

Options: `--dest DIR` overrides the cache root (same resolution as the export and ingest
skills), `--limit N` sets the row cap (default 50), `--width N` the per-cell character cap
(default 200). If the index does not exist yet, run `../transcript-ingest/transcripts.py`
first.

## Worked queries

Tool use, ranked, with failure counts:

```sql
SELECT name, count(*) AS n, sum(is_error) AS errs
FROM tool_calls GROUP BY 1 ORDER BY n DESC
```

Where the work happened:

```sql
SELECT project_key, count(*) AS sessions
FROM sessions GROUP BY 1 ORDER BY sessions DESC
```

Activity by month:

```sql
SELECT substr(started_at, 1, 7) AS month, count(*) AS sessions
FROM sessions WHERE started_at IS NOT NULL GROUP BY 1 ORDER BY 1 DESC
```

Which tools fail most, ignoring rare ones:

```sql
SELECT name, round(100.0 * sum(is_error) / count(*), 1) AS pct_error
FROM tool_calls GROUP BY 1 HAVING count(*) > 100 ORDER BY pct_error DESC
```

Main conversations versus subagent transcripts:

```sql
SELECT harness, kind, count(*) FROM sessions GROUP BY 1, 2
```

## Full-text search

The `messages_fts` index searches message text. Search returns **where** something was
discussed, not the text itself:

```sql
SELECT s.harness, s.native_id, count(*) AS hits
FROM messages_fts
JOIN messages m ON m.id = messages_fts.rowid
JOIN sessions s ON s.id = m.session_id
WHERE messages_fts MATCH ?
GROUP BY 1, 2 ORDER BY hits DESC
```

Two traps, both of which fail loudly:

- **Match against the table name, never a table alias.** `WHERE f MATCH ?` with `f` as an
  alias raises "no such column: f". Write `messages_fts MATCH ?`.
- **Quote any term containing a hyphen or punctuation.** A bare `force-with-lease` is parsed
  as FTS5 operators and raises a syntax error; pass it as `"force-with-lease"`, quotes
  included, so it is one phrase. (`search.py` and `excerpt.py` auto-quote hyphenated tokens
  for you.)

## Hunting a topic: `search.py`, `excerpt.py`, `cluster.py`

A plain FTS `MATCH` over `messages_fts` returns **where** a term appears, but it is noisy:
the harness injects standing instructions (e.g. the AGENTS.md "always check for a dev
container first" rule) into every session, so a term that appears in one of those shows up in
hundreds of sessions that never actually discussed it. Three sibling scripts close that gap.
They are read-only and cap output exactly like `query.py`.

### `search.py` — which sessions, with two noise knobs

`search.py` builds the FTS join for you and adds the two knobs that make a real hunt usable:

```bash
# Drop the injected standing-instruction messages, then rank by error context.
uv run --script ./search.py --term 'devcontainer' --harness dsh --exclude-injected --errors
# Only sessions with >= 3 real mentions.
uv run --script ./search.py --term '"devcontainer-cli"' --min-hits 3
```

- `--exclude-injected` drops messages the ingest `annotate` pass flagged as standing
  instructions, so hit counts reflect what a session actually *did*.
- `--errors` sorts by the number of matches that also carry a failure signal (`error`,
  `failed`, `permission denied`, `not found`, `exit code`, …), so problem sessions float up.
- `--harness` / `--roles` narrow to a harness and/or role; `--min-hits` filters the tail.

### `excerpt.py` — bounded, durable per-session excerpts

When you have a matched set and need to read (or hand to a subagent) what each session
actually said, `excerpt.py` writes one capped file per session plus a `manifest.json`, into a
durable, non-repo work dir (default `<cache>/work/<run>/`):

```bash
uv run --script ./excerpt.py --term 'devcontainer' --harness dsh --run devcontainer-audit
# Explicit sessions, then read the messages AFTER the head window.
uv run --script ./excerpt.py --ids 18651,18761 --run devcontainer-audit
uv run --script ./excerpt.py --next 18651 --offset 30 --count 30
```

Each excerpt file has a header (session id, native id, title, project, started, matching
count, `truncated`), the first main-path user message, a **head** sample and a **tail** sample
of the matching messages, and a `… [N messages omitted between head and tail]` marker when the
sample was truncated. The manifest records the query, caps, and per-session `truncated` /
`total_matches` so a follow-up agent knows when an excerpt is incomplete and can pull the next
chunk with `--next`. `--exclude-injected` and `--no-user` tune what goes in.

### `cluster.py` — group judged sessions by shared failure signature

After a batch of subagents returns one-line verdicts, `cluster.py` groups sessions that share a
failure signature (a rootless docker socket path, a `devcontainer.json` lifecycle command,
"permission denied", "not found", …) so a recurring theme surfaces as one group with its
session ids instead of being buried across verdict lines:

```bash
cat verdicts_*.txt | uv run --script ./cluster.py --min 2
```

Input is the verdict format (`<id>|VERDICT=…|SEVERITY=…|<summary>`) or a `<id><TAB><summary>`
TSV. `--min` sets the smallest cluster to report; `--json` emits the groups as data.

### `verdict.schema.json` — validated subagent verdicts

When fanning out excerpt readers, pass `verdict.schema.json` as the `schema` of a
workflow/`agent()` call so each subagent returns `{session_id, verdict, severity, summary,
evidence}` (validated, aggregatable) instead of prose that has to be re-parsed.

## Reading one message

When a count cannot settle a question, resolve a single message id from the search above and
read that one row:

```bash
uv run --script ./query.py "SELECT role, ts, text FROM messages WHERE id = ?" 12345 --width 2000
```

That is the sanctioned path for prose, one message at a time. To judge many flagged cases,
hand each excerpt to a separate cheap subagent and collect verdicts, so the bulk of the text
never lands in the orchestrating context.

## Privacy invariants

- **Query results and anything derived from them never enter a git repo.** Counts may be
  summarized for the user; message text stays on device.
- The database is as sensitive as the raw transcripts it was built from.
- Read-only access only. Rebuilding or repairing the index is the ingest skill's job.

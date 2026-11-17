---
name: transcript-query
description: Query the agent-transcripts sqlite index to measure tool use, sessions, projects and activity across Claude Code, pi and dsh without loading transcript prose into context. Use when the user wants to "query transcripts", "how often did I use X", "find sessions where …", or any question answered from chat history. Aggregates first, bounded excerpts only where judgment is required.
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
- Selecting `text` across many rows: never. Group and count instead.
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
(default 200). If the index does not exist yet, run
`uv run --script ../transcript-ingest/transcripts.py ingest` first.

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

A Claude `subagent` is any file under a session's `subagents/` directory, and its
`parent_native_id` is that session. That includes Workflow agents, which sit at
`subagents/workflows/<run>/agent-<id>.jsonl`; each run's `journal.jsonl` there is a
`subagent` row with no messages. Count Workflow agents by their file:

```sql
SELECT count(*) AS workflow_agents
FROM sessions s JOIN files f ON f.id = s.file_id
WHERE s.harness = 'claude' AND f.relpath LIKE '%/subagents/workflows/%/agent-%'
```

Tokens processed per harness. `input_tokens` excludes the prompt cache on every harness,
so summing it alone undercounts a cache-heavy session by an order of magnitude; add the
cache columns (`NULL` where the harness did not report them). Each Claude API call's usage
sits on one row of its response, the others `NULL`, so these sums count every call once:

```sql
SELECT harness, sum(input_tokens) AS uncached, sum(cache_read_tokens) AS cache_read,
       sum(cache_write_tokens) AS cache_write,
       sum(coalesce(input_tokens, 0) + coalesce(cache_read_tokens, 0)
           + coalesce(cache_write_tokens, 0)) AS prompt_processed,
       sum(output_tokens) AS output
FROM messages GROUP BY 1
```

How much a session says, without tool traffic. Tool results are their own `tool_result`
rows and call arguments live in `tool_calls`; an assistant message that makes calls has
empty text. So user plus assistant text is the conversation itself (`system` rows are
counted apart because they are mostly harness text):

```sql
SELECT s.native_id,
       sum(CASE WHEN m.role IN ('user', 'assistant') THEN length(m.text) END) AS chat,
       sum(CASE WHEN m.role = 'system' THEN length(m.text) END) AS system_rows,
       sum(CASE WHEN m.role = 'tool_result' THEN length(m.text) END) AS results
FROM sessions s JOIN messages m ON m.session_id = s.id
WHERE s.kind = 'main' AND s.started_at >= ?
GROUP BY 1 ORDER BY chat DESC
```

`../transcript-analyze/corpus.py sizes` prints the same split as percentiles.

## Schema facts that change answers

Each was confirmed against a real index; get one wrong and a count or a judgment is wrong.

- **`on_main_path = 0` is not "off to the side".** Every message before a compaction is off
  the main path, and so is every message the user typed while the agent was working. In
  long sessions most messages are off it (seen 2026-11-16). For the whole conversation,
  order by `ord` and do not filter on `on_main_path`.
- **`injected` is a frequency guess, not a source label.** The ingest `annotate` pass marks
  text seen in several sessions. Before 0.14.0 that also caught short human replies ("yes",
  "go", "commit and push": 770 rows in one index, seen 2026-11-16); it now skips user rows
  under 200 characters, from the next ingest that parses anything (or
  `transcripts.py annotate`). Use it to drop standing instructions from a search, never to
  decide whether the human said something. To strip harness text from a user row, remove
  `<system-reminder>` and similar blocks by structure, as `review.py` does.
- **Mid-turn messages are ordinary `user` rows** (ingested from `queued_command`
  attachments, `on_main_path = 0`). A copy may also appear inside a `tool_result`; the
  `user` row is the one to count.
- **`system` rows are mostly harness text,** distinguishable by their opening:
  `Base directory for this skill:` (a skill body, reloaded on every invocation; one
  scheduled session reloaded skills 677 times, 26 million characters),
  `This session is being continued from a previous` (a compaction summary),
  `<agent-message` or `Another Claude session sent a message` (a subagent's or peer's
  report), `<task-notification>`.
- **A final report may live in `tool_calls.arguments`, not in message text.** A subagent or
  headless run that answers through `StructuredOutput` or `SubagentHandback` leaves its
  message text empty. Read it with
  `SELECT name, arguments FROM tool_calls WHERE message_id = ?`, or
  `../transcript-review/review.py expand <session> <ord>`.
- **A background subagent's result is not its report.** The `Agent` call's result says the
  agent was launched; the report arrives later as a `system` row. The subagent's own session
  has `parent_native_id` set to the parent and its first user message equal to the call's
  `prompt` argument, which is how to join them.
- **Scripted sessions can be half of a window.** Headless review rounds and scheduled jobs
  open with a long template, which counts as user text, so they top any "most user text"
  ranking (121 of 245 recent main sessions in one index, seen 2026-11-16). Tell them apart
  by a shared long opening, as `corpus.py plan` does.

## Full-text search

The `messages_fts` index searches message text. Search returns **where** something was
discussed, not the text itself. It is built after each full ingest, not per row, so for a
few minutes after a rebuild it lags the messages; `search.py` and `excerpt.py --term` check
`meta` first and refuse a stale index with `full-text index is stale; run: uv run --script
…/transcript-ingest/transcripts.py fts` and exit 2. Run that command (or wait for the
ingest that is building it) and retry. A hand-written `MATCH` in `query.py` gets no such
check: it is current only when `meta.fts_dirty = 0` and `meta.fts_max_id >= max(messages.id)`.

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
  instructions, so hit counts reflect what a session actually *did*. On an index annotated
  before 0.14.0 it also drops short human replies (see "Schema facts that change
  answers").
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

When fanning out excerpt readers, have each return JSON matching `./verdict.schema.json`
— `{session_id, verdict, severity, summary, evidence}` (validated, aggregatable) instead of
prose that has to be re-parsed. On Claude Code, pass the schema as the `schema` of a workflow
`agent()` call; on other harnesses, validate each child's reply against it. To cluster JSON
verdicts, convert them to the TSV form first:
`jq -r '"\(.session_id)\t\(.summary)"' verdicts.jsonl | uv run --script ./cluster.py --min 2`.

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

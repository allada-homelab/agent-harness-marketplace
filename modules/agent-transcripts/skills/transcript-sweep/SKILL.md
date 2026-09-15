---
name: transcript-sweep
description: Sweep the agent-transcripts sqlite index for sessions worth a closer look and record flagged tool errors, retry loops, duplicate calls, shell commands a dedicated tool covers, and oversized results or sessions in the findings store beside it. Use when the user wants to "sweep transcripts", "find problem sessions", "where did tools fail", or a first pass before analyzing agent behavior. Deterministic — a script does the counting, and the model only reports the summary and where it landed.
tags: [observability]
---

# transcript-sweep

The first pass over the index the `transcript-ingest` skill builds. A script scans every
tool call and writes one row per session per flag kind into `findings.db`, the store beside
the index; a later analysis skill reads that store. Your job here is three steps: run the
script, read its summary, report it.

## Run it

```bash
uv run --script ./sweep.py
```

Useful narrowing, all optional:

- `--harness claude|pi|dsh` — one harness; repeat the flag for two.
- `--since 2026-06-01` — only sessions started at or after this ISO8601 timestamp.
- `--session <id>` — one session, by native id or numeric id.
- `--out PATH` — also write a JSONL copy of every record there. Without it the run writes
  nothing but the store.
- `--no-db` — skip the store; only `--out`, if given, is written.
- `--long-result 5000`, `--long-session 150` — the two size thresholds.
- `--top 20` — how many sessions the summary ranks.
- `--dest DIR` — the cache root, same resolution as the export, ingest and query skills.

If it exits 2 saying the index is at an older parser version, run the `transcript-ingest`
skill first; the sweep needs what the current parser records. Finding flags is not a failure:
a run with thousands of flags still exits 0.

## What it writes

`findings.db`, beside `transcripts.db` in the cache root — the primary output, and the one a
later skill reads. Each run appends a row to `runs` and rewrites `sweep_flags` for every
session it scanned, so a re-sweep replaces a session's flags and retires the ones that are
gone. Rows are keyed by harness and native session id, never by the index's row ids, so the
store survives an `ingest --rebuild`.

The JSONL is optional and secondary: pass `--out PATH` when something outside this skill
needs a flat file. Without it nothing but the store is written.

## What it flags

Severity `issue` — something went wrong:

- `tool_error` — tool calls that returned an error, grouped by an error signature
  (permission denied, edit anchor miss, file not found, non-zero exit, other).
- `error_streak` — three or more failing tool calls in a row.
- `retry_same_input_after_error` — a failed call repeated with the same arguments within the
  next two calls.

Severity `potential` — maybe fine, maybe waste:

- `duplicate_call` — the same tool with the same arguments called more than once in a session.
- `bash_substitute` — a shell call whose whole command is one `cat`, `head`, `tail`, `grep`,
  `rg`, `find`, `ls` or `sed -n` that a dedicated tool covers. Chained one-liners are not
  flagged; they are legitimate.
- `long_result` — a tool result longer than the `--long-result` threshold.
- `long_session` — a session with more tool calls than the `--long-session` threshold.

## Read the summary

Stdout gives you, in order: how many records the run produced (and the JSONL path if `--out`
was given), the findings store path and this run's id, a table of counts by harness and flag
kind, how many sessions were scanned versus flagged, and the top sessions ranked by issue
count. That is the whole report. Repeat it to the user, with the store path and run id, and
stop.

## Rules

- **Never open a raw transcript in this skill**, and never read the flag bodies in bulk —
  the index holds the user's entire chat history. The script already caps every quoted
  snippet at 200 characters.
- **Do not judge the flags here.** A flag is a candidate, not a verdict; interpreting them is
  a separate analysis skill's job.
- **Read-only on the index.** The sweep opens `transcripts.db` read-only; it writes only the
  findings store and, when asked, the JSONL.
- **The findings stay on device.** Like the index, they are derived from private transcripts
  and never enter a git repo.

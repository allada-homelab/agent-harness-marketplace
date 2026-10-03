# agent-transcripts

Export Claude Code, pi and dsh transcripts into one on-device cache and index them in a
derived sqlite database. Eight portable skills: `transcript-export-claude`,
`transcript-export-pi` and `transcript-export-dsh` each do a read-only, incremental export
of one harness's raw session files (host directories plus dev-container docker volumes for
claude and dsh) into a cache root outside any git worktree, `transcript-ingest` builds
the derived sqlite index over everything exported, `transcript-query` reads it to answer
questions about tool use, sessions and activity across harnesses, `transcript-sweep`
scans it for sessions worth a closer look, `transcript-review` judges those sessions one
at a time, and `transcript-analyze` reads one whole session and writes an analysis of it.
The raw files are
canonical; the database is rebuildable and safe to delete. The three export skills call the
one script that ships beside the ingest skill.

Because the index holds the user's whole chat history, `transcript-query` is built around
aggregates: its helper caps every cell and every result set, so answering a question does not
empty transcript prose into the context asking it.

The query skill ships four scripts. `query.py` runs one arbitrary capped SELECT. `search.py`
answers "which sessions talk about X" and adds two knobs for a real hunt: `--exclude-injected`
drops the standing instructions the ingest `annotate` pass flags as `injected`, and `--errors`
ranks by matches that also carry a failure signal. `excerpt.py` writes bounded per-session
excerpts (head/tail sampling, truncation flags, a `manifest.json`) into a durable, non-repo
work dir, with `--next` to pull the messages after the head window. `cluster.py` groups judged
sessions by shared failure signature, and `verdict.schema.json` validates a fan-out of excerpt
readers. The ingest `annotate` pass marks a message `injected` when it is a `system` message or
a non-`tool_result` message repeated across several sessions — the standing-instruction
signature — so those scripts can filter it out.

## The sweep

`transcript-sweep` is the deterministic first pass between indexing and analysis: one
ordered scan of the index flags tool errors, error streaks, retries of a failed call,
duplicate calls, shell one-liners a dedicated tool covers, and oversized results or
sessions, then writes one JSONL record per session per flag kind. Only the script reads
transcripts — the model reads a counts summary and reports where the JSONL landed — so a
small local model can run it. Judging the flags is a later skill's job.

## The review

`transcript-review` is the semantic second pass: the sweep sees what SQL can count, this
skill sees what only reading can find — a failing approach retried unchanged, a tool used
against its contract, the user having to interrupt, work claimed done with nothing in the
session showing it. Its script does everything mechanical. `queue` picks candidates (sessions
the sweep flagged heavily, sessions whose last turn is the user's, sessions holding a short
correction, plus a seeded random sample as a control), `view` renders exactly one session
capped to a character budget with every injected harness block — system reminders, task
notifications, hook output, runtime-context snapshots — replaced by a `[stripped: …]` marker
and every line labelled with its message ord, and `record` validates the verdict: all
thirteen rubric categories answered, and every `present` finding carrying an ord and a quote
that really occurs in that message. A quote a model invented is rejected, so a small local
model reading one view at a time can do the judging. The session's final report — the last
assistant text and a subagent's `SubagentHandback` arguments — is shown in full and never
elided, and `grep` searches one whole session, elided messages included, so a claim is checked
against its evidence rather than against what fit the budget. `rollup` counts what
accumulated, by category, tool, project or week.

## The analysis

`transcript-analyze` reads a whole session instead of a budgeted view of it, for the
questions a rubric cannot answer: what the session set out to do, where it turned, why it
ended the way it did, and what to change. Tool results are 53–75% of a session's
characters, so `read` hides them, showing each as its size, except a failed result's first
160 characters and a subagent's report. It caps call arguments at 200 characters and
splits the rest into pages of about 30,000 characters, preferring to break at a user turn.
`expand` shows any hidden text on demand. `record-analysis` refuses an analysis unless the
run logged a read of every page and every cited quote occurs in its message. `themes`
groups recorded analyses by outcome, problem category and label, and recommendation
target. Its commands live in `transcript-review`'s script, which they share code with. A
session longer than four pages is split across child agents.

All three passes write `findings.db`, a small sqlite database beside the index in the cache root,
keyed by `(harness, native_id)` so findings survive rebuilding the index. Like the index it
is derived from private transcripts and never enters a git repo.

## Install

- Claude Code: `/plugin marketplace add allada-homelab/agent-harness-marketplace` then
  `/plugin install agent-transcripts@agent-harness-marketplace`
- pi: the whole repo installs as one package
  (`pi install git:github.com/allada-homelab/agent-harness-marketplace`); narrow with
  `settings.packages`
- dsh: `dsh plugin --profile <p> add "github:allada-homelab/agent-harness-marketplace#v0.1.0&path:/modules/agent-transcripts"`

Tests: `uv run --with pytest --with zstandard --python 3.12 pytest -q modules/agent-transcripts/test`.

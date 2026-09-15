# agent-transcripts

Export Claude Code, pi and dsh transcripts into one on-device cache and index them in a
derived sqlite database. Six portable skills: `transcript-export-claude`,
`transcript-export-pi` and `transcript-export-dsh` each do a read-only, incremental export
of one harness's raw session files (host directories plus dev-container docker volumes for
claude and dsh) into a cache root outside any git worktree, `transcript-ingest` builds
the derived sqlite index over everything exported, `transcript-query` reads it to answer
questions about tool use, sessions and activity across harnesses, and `transcript-sweep`
scans it for sessions worth a closer look. The raw files are
canonical; the database is rebuildable and safe to delete. The three export skills call the
one script that ships beside the ingest skill.

Because the index holds the user's whole chat history, `transcript-query` is built around
aggregates: its helper caps every cell and every result set, so answering a question does not
empty transcript prose into the context asking it.

## The sweep

`transcript-sweep` is the deterministic first pass between indexing and analysis: one
ordered scan of the index flags tool errors, error streaks, retries of a failed call,
duplicate calls, shell one-liners a dedicated tool covers, and oversized results or
sessions, then writes one JSONL record per session per flag kind. Only the script reads
transcripts — the model reads a counts summary and reports where the JSONL landed — so a
small local model can run it. Judging the flags is a later skill's job.

## Install

- Claude Code: `/plugin marketplace add allada-homelab/agent-harness-marketplace` then
  `/plugin install agent-transcripts@agent-harness-marketplace`
- pi: the whole repo installs as one package
  (`pi install git:github.com/allada-homelab/agent-harness-marketplace`); narrow with
  `settings.packages`
- dsh: `dsh plugin --profile <p> add "github:allada-homelab/agent-harness-marketplace#v0.1.0&path:/modules/agent-transcripts"`

Tests: `uv run --with pytest --with zstandard --python 3.12 pytest -q modules/agent-transcripts/test`.

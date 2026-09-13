# agent-transcripts

Export Claude Code, pi and dsh transcripts into one on-device cache and index them in a
derived sqlite database. Four portable skills: `transcript-export-claude`,
`transcript-export-pi` and `transcript-export-dsh` each do a read-only, incremental export
of one harness's raw session files (host directories plus dev-container docker volumes for
claude and dsh) into a cache root outside any git worktree, and `transcript-ingest` builds
the derived sqlite index over everything exported. The raw files are canonical; the database
is rebuildable and safe to delete. The three export skills call the one script that ships
beside the ingest skill.

## Install

- Claude Code: `/plugin marketplace add allada-homelab/agent-harness-marketplace` then
  `/plugin install agent-transcripts@agent-harness-marketplace`
- pi: the whole repo installs as one package
  (`pi install git:github.com/allada-homelab/agent-harness-marketplace`); narrow with
  `settings.packages`
- dsh: `dsh plugin --profile <p> add "github:allada-homelab/agent-harness-marketplace#v0.1.0&path:/modules/agent-transcripts"`

Tests: `uv run --with pytest --with zstandard --python 3.12 pytest -q modules/agent-transcripts/test`.

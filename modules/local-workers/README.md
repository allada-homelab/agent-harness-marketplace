# local-workers

Explicitly requested delegation to self-hosted models: a `pi-run` command, one MCP tool and one skill.
Claude Code only (the skill is scoped `harness: [claude]`).

| Worker | Backend | What it does |
|---|---|---|
| `pi-run` (`bin/`, on the Bash `PATH`) | the pi agent | One task, brief on stdin or as arguments; prints pi's final answer. Every run is a resumable session; options in `pi-run --help` |
| `decide` | d3-ultra-INT4 on vllm-srun (`decision-default`) | A batch of ≤ 128 `choice` / `noul` / `score` questions; flags floored, low-confidence and truncated answers |

The `delegate` skill loads only when a request names pi or the local decision model (generic
"local LLM" / homelab requests stay with the `local-llm` plugin), and tells Claude how to brief pi, batch decisions, and verify results before relaying them.
Nothing here ever falls back to an Anthropic model: failures come back as typed results.

## Requirements

- `uv` on PATH (the server runs as `uv run --script` with inline dependencies; no install step).
- `pi` 1.4 or later on PATH, already configured, with the `llama-swap/large-default` model
  (`pi-run`'s default; `--model` overrides it).
- `timeout` and `flock` (util-linux) on PATH.
- Network access to the decision shim (default `http://10.69.1.169:8690/upstream/decision-default`).

## Configuration

Set in `/config` (plugin options) or at enable time:

| Option | Default |
|---|---|
| `decision_url` | `http://10.69.1.169:8690/upstream/decision-default` |
| `decide_concurrency` | 8 |

## Behaviour worth knowing

- `pi-run` is `pi -p` with your normal pi config. Its exit status is pi's: text mode exits 1 when the
  run errored or the answer was truncated (pi 1.4 `dist/modes/print-mode.js`); `timeout` makes it 124.
- Sessions live in `${XDG_STATE_HOME:-~/.local/state}/pi-run/<id>/` (pi's session file plus the
  directory the run started in) and are pruned after 14 days. pi scopes sessions to a directory, so a
  follow-up from elsewhere would silently start blank; `pi-run` `cd`s back instead. To open one in the
  TUI: `cd "$(cat <dir>/cwd)" && pi --session-dir <dir> --continue`.
- A session runs one brief at a time (`flock` on its dir); a busy session refuses `--session` and
  `--fork` with exit 2.
- switchboard's hooks are switched off inside a run (`PI_HOOK_EXCLUDE_MODULES`): they registered each
  delegated run as a peer session and injected the roster, which derailed a forked follow-up.
- `decide` marks any yes/no with P between 0.199 and 0.801 `floored` (a coin flip, not a decision).
  The server rejects a record plus question over 22,528 tokens; that item comes back `invalid`.
  The client still speaks the retired H2O shim (its clamped floor, its truncation flag) for rollback.

## Development

```bash
# from the repo root: unit + stdio protocol tests (a fake pi on PATH, a fake shim) run in bin/check.sh
uv run --with pytest --with 'mcp>=2.1,<3' --python 3.13 pytest -q modules/local-workers/test
LW_LIVE_TESTS=1 uv run --with pytest --with 'mcp>=2.1,<3' --python 3.13 pytest -q modules/local-workers/test/test_live.py
claude plugin validate modules/local-workers

# Behaviour evals against the real decision model. pi itself cannot run inside an eval (a Bash grant
# puts every command in a sandbox that cannot read the home directory, where pi and its config live),
# so the pi cases only grade whether a `pi-run` Bash call was made.
cd modules/local-workers && claude plugin eval . --trust-plugin --mocks off \
  --allow-tools "mcp__plugin_local-workers_local__*" Bash --scaffold --ablation none
```

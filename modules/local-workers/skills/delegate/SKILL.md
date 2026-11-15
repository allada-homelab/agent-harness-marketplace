---
name: delegate
description: >-
  Hand work to David's self-hosted pi agent or local decision model — the pi-run script (the pi coding agent on the local LLM, with resumable and forkable sessions) and the decide MCP tool (the d3-ultra decision model: batched yes/no, choice and score questions). Use ONLY when the request names pi or the decision model, e.g. "use fanned-out local pi agents to read each file and summarize", "have pi check…", "ask the local decision model which of these…". Requests to run on the local LLM, local subagents or homelab models that name neither pi nor the decision model belong to the local-llm plugin, not this skill.
harness: [claude]
---

# Delegating to local workers

Two workers: the `pi-run` command (on your Bash `PATH` while this plugin is enabled) and the
`decide` tool from the `local` MCP server. Both run on David's GPUs, cost no API spend, and **never
fall back to a paid model** — a failure comes back as a result. Accuracy outranks savings: an answer
that cannot be trusted is reported as such, never passed off.

| Worker | Use for | Not for |
|---|---|---|
| `pi-run` | Reading, extracting, summarizing, comparing files; finding where something is; well-specified edits and commands | Judgement calls the answer rests on |
| `decide` | A fixed question with enumerable answers about each of many records: classify, route, yes/no, rate | Open-ended questions, counting, arithmetic, anything needing explanation |

Work that fits neither stays with you.

## pi-run

pi runs on `llama-swap/large-default` with David's own tools, extensions and context files, in the
directory you call it from. It sees **nothing** from this conversation, so every brief is
self-contained:

1. The goal in one sentence.
2. Exact paths (absolute, or relative to the directory you run it in).
3. The output format, e.g. "Reply as: `<file>: <one-line summary>`, then up to 5 bullets".
4. "Cite file:line for each claim. If the files don't say, write UNKNOWN — do not guess."

Pass the brief on stdin with a quoted heredoc, so nothing in it is shell-expanded:

```bash
pi-run --read-only <<'EOF'
<the brief>
EOF
```

stdout is pi's final answer. stderr starts with `pi-run: session <id>`. Exit status is pi's: non-zero
means the run errored or its answer was truncated, 124 means it timed out, 2 a usage error.

| Option | Use |
|---|---|
| `--read-only` | Only read, grep, find and ls. Use it for every reading task and for any fan-out over one tree, so parallel runs cannot edit under each other |
| `--session ID` | Send a follow-up to an earlier run; pi keeps its context and works in the directory that run started in |
| `--fork ID` | A new session that starts from ID's history. Use it for parallel follow-ups: one session runs one brief at a time, and a busy session refuses a second (exit 2) |
| `--file PATH` | Inline a file (text or image) into the brief instead of making pi read it; repeatable |
| `--model M` | Only when David explicitly names another model for this task (`provider/id[:thinking]`); never pick one yourself |
| `--thinking L` | Thinking level; `--thinking low` suits trivial lookups |
| `--timeout SECS` | Wall-clock limit, default 1800 |

- **One unit of work per run.** To fan out, issue the Bash calls **in parallel in one message**, at most
  4 at a time: large-default serves 4 sequences, and extra runs queue on the GPU while their timeout
  runs.
- **Long runs go in the background.** Anything that may pass 2 minutes runs with Bash
  `run_in_background`, so a slow model never hits the Bash tool's own time limit.
- **Prime once, then fork.** For several questions about the same large material, have one run read
  it, then `--fork` that session once per question.
- **Edits are pi's, not yours.** Without `--read-only` pi can change files and run commands. Brief
  edits precisely, give each writer its own files, and read the diff before you build on it.

## decide

Read `references/decision-types.md` before the first `decide` call in a session — it has the exact
shapes and real responses for all three types (`choice`, `noul`, `score`), images, and the flags.

- **Batch only.** One call with every record, ≤ 128 questions in total; split larger jobs.
- **One item per record**, all its questions together (they share the record's cache).
- `noul` instructions are statements to judge true/false, not questions.
- **When the record may not contain the answer, don't ask a `noul`.** Ask a `choice` with an explicit
  option such as `"not_stated": "The record does not say"`. A `noul` whose false side means "no, or not
  stated" comes back as a confident "no" and hides the gap.
- Give `choice` a "none of the above" option whenever none may apply.
- **~22K limit:** a record plus question over 22,528 tokens comes back `status: invalid`
  (`max_length_exceeded`), never truncated. Extract the relevant part first (`pi-run` can) or split it.

## Verify before you relay (required)

- **pi-run:** treat its answer as an unverified draft. Before you report anything to David that the
  answer depends on, check it against the file yourself (open the cited `file:line`). Say which
  claims you checked. If a check fails, discard that result, do the work yourself, and tell David
  the local run was wrong.
- **decide:** `floored`, `low_confidence` and `possibly_truncated` answers are **no decision**. A
  floored `noul` (P between 0.199 and 0.801) is a coin flip, not "no" — `threshold`/`decision` does
  not change that.
  Decide those yourself or report them as undecided, and say how many there were.
- **One resolved answer per item.** Where you settle a flagged item yourself, put your value in the
  result and mark it, e.g. "not breaking (my call; model undecided)". Leave an item undecided only when
  the record genuinely doesn't say.
- **Errors:** report a non-zero `pi-run` exit (with its stderr), an empty answer, and `decide`
  errors plainly. Do the work yourself only if David
  asked for the task to be done regardless of worker.

## Report

End with one line of accounting: how many pi runs / decisions ran locally, how many results you
checked or overrode, and any failures.

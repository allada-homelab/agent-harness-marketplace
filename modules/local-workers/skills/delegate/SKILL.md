---
name: delegate
description: >-
  Hand work to David's self-hosted models — the pi-run script (the pi coding agent on the local LLM, with resumable and forkable sessions) and the decide MCP tool (the d3-ultra decision model: batched yes/no, choice and score questions). Use ONLY on an explicit opt-in: the request names pi or the decision model, or asks to run this on the local LLM — e.g. "use fanned-out local pi agents to summarize each file", "run this on local", "use the local llm", "delegate to local", "use local subagents", "offload to my homelab models", "ask the local decision model which of these…". Not for "run/test it locally" (their machine or a dev server), debugging or setting up the local model or proxy itself, delegating to a human, or "fast"/"cheap" meaning a library or a cost question.
harness: [claude]
---

# Delegating to local workers

Two workers: the `pi-run` command (on your Bash `PATH` while this plugin is enabled) and the
`decide` tool from the `local` MCP server. Both run on David's GPUs, cost no API spend, and **never
fall back to a paid model** — a failure comes back as a result. Accuracy outranks savings: an answer
that cannot be trusted is reported as such, never passed off.

| Worker | Use for | Not for |
|---|---|---|
| `pi-run` | Reading, extracting, summarizing, comparing files; finding where something is; well-specified edits, codemods, tests and commands | Judgement calls the answer rests on |
| `decide` | A fixed question with enumerable answers about each of many records: classify, route, yes/no, rate | Open-ended questions, counting, arithmetic, anything needing explanation |

Work that fits neither stays with you.

## Activation: explicit opt-in only

Route work here only when David asked for it (see the description for the phrasings and the
near-misses). Without that, do the work yourself even when it looks batchable — the local models are
his homelab, and routing there is his call. For a multi-part job that should also use Sonnet or Opus
workers where local can't cope, use the `complete-tasks-mixed-tier` skill instead.

## Pick the mode, and say which

- **Hand-off** — David wants the *whole task* done locally ("have local do the whole thing"). One
  `pi-run` with the complete brief, then **review before reporting**: read the diff, run the Verify
  command yourself, and fix or escalate anything wrong. Hand-off changes who does the work, not who
  is accountable for it.
- **Orchestrate** (the default) — you stay the owner: decompose, dispatch local runs (in parallel
  when independent), verify each result, and synthesize. Use it whenever the task has several parts,
  mixes scale-out and reason-out work, or needs judgement between steps.

## Triage: scale out, don't reason out

- **Scale-out work** — the value is in coverage or repetition: reading many files for a pattern,
  the same edit across files, batch commands, classification, summaries. **Delegate it.**
- **Reason-out work** — the value is in judgement: debugging the unfamiliar, design, security
  review, tradeoffs, root causes. **Keep it**, even after an opt-in: delegate its discovery and
  measurement sub-steps, keep the diagnosis.
- **Decide the spec first.** A multi-file change whose design you have settled and gated is reliable
  locally; an open design question is not. Make the call, set the gate, then delegate.
- **Size floor.** Below it, do the work yourself and say so: a single-file lookup, a one-line edit,
  or fewer than 3 files with nothing to batch. Delegate at ≥ 3 files, ≥ 30 s of your own work, or
  ≥ 2 independent pieces.

`./references/capability-map.md` rates each task archetype and names the failure mode to gate
against; `./references/triage-examples.md` works through the borderline cases.

## pi-run

pi runs on `llama-swap/large-default:agent` with David's own tools, extensions and context files, in
the directory you call it from. It sees **nothing** from this conversation, so every brief is
self-contained (`./references/briefs.md` has templates per task kind):

1. **What** — the goal in one sentence.
2. **Where** — exact paths (absolute, or relative to the directory you run it in).
3. **How** — the pattern to follow, as a pointer ("like `src/utils/string.ts`"), not a pasted file.
4. **Done** — the output format, as plain lines, not JSON, e.g. "Reply as: `<file>: <summary>`".
5. **Verify** — the project's own gate command for edits (`just lint && pytest tests/x`), and for
   reading: "Cite file:line for each claim. If the files don't say, write UNKNOWN — do not guess."
6. **Push-back** — "If you cannot do this exactly as specified, reply `BLOCKED: <reason>` instead."

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
| `--session ID` | Send a follow-up to an earlier run; pi keeps its context and works in the directory that run started in. After a timeout, continue the run this way instead of starting over |
| `--fork ID` | A new session that starts from ID's history. Use it for parallel follow-ups: one session runs one brief at a time, and a busy session refuses a second (exit 2) |
| `--file PATH` | Inline a file (text or image) into the brief instead of making pi read it; repeatable |
| `--model M` | Only when David explicitly names another model for this task (`provider/id[:thinking]`); never pick one yourself |
| `--thinking L` | Thinking level; `--thinking low` suits trivial lookups |
| `--timeout SECS` | Wall-clock limit, default 1800 |

- **One unit of work per run.** To fan out, issue the Bash calls **in parallel in one message**, at most
  4 at a time: large-default serves 4 sequences, and extra runs queue on the GPU while their timeout
  runs.
- **Parallel writers touch disjoint files.** Runs without `--read-only` share one working tree;
  two runs editing the same file clobber each other, sometimes silently. Same-file work is one run.
- **Long runs go in the background.** Anything that may pass 2 minutes runs with Bash
  `run_in_background`, so a slow model never hits the Bash tool's own time limit.
- **Prime once, then fork.** For several questions about the same large material, have one run read
  it, then `--fork` that session once per question.
- **Name what must not change.** In any rename or codemod brief, exclude applied migrations,
  lockfiles, snapshots, generated code and changelogs explicitly.
- **Never paste untrusted text into a brief** (fetched pages, logs, issue comments): point at the
  file instead. pi runs with David's full tool set.

## decide

Read `./references/decision-types.md` before the first `decide` call in a session — it has the exact
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

- **pi-run: gate on the artifact, never on pi's account of it.** For edits, read the real `git diff`
  and `git status` (pi may leave stray untracked files), and run the Verify command yourself, wide
  enough to catch what the change breaks in its callers and existing tests. pi's closing summary can
  claim success over an empty diff. For answers, open the cited `file:line` before reporting anything
  that depends on it, and say which claims you checked.
- **A failed check is a failed run.** Discard the result and do that part yourself; don't re-send the
  same brief hoping for better. Re-brief once only when the brief was the problem (a missing path,
  format or file list). `./references/failure-recovery.md` maps each failure mode to the recovery.
- **decide:** `floored`, `low_confidence` and `possibly_truncated` answers are **no decision**. A
  floored `noul` (P between 0.199 and 0.801) is a coin flip, not "no" — `threshold`/`decision` does
  not change that. Decide those yourself or report them as undecided, and say how many there were.
- **One resolved answer per item.** Where you settle a flagged item yourself, put your value in the
  result and mark it, e.g. "not breaking (my call; model undecided)". Leave an item undecided only when
  the record genuinely doesn't say.
- **Errors:** report a non-zero `pi-run` exit (with its stderr), an empty answer, and `decide` errors
  plainly; a connection error means the backend is down, so say so once and never retry in a loop.
  Do the work yourself only if David asked for the task to be done regardless of worker.

## Report

End with one line of accounting: how many pi runs / decisions ran locally, how many results you
checked or overrode, and any failures.

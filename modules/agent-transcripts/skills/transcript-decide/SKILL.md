---
name: transcript-decide
description: Label agent sessions with an optional decision model — fixed batteries of yes/no and choice questions about every human turn (correction, approval, frustration) and every session's request and final report (claimed outcome, tests claimed, shipped, open items, task kind) — and store the probabilities in the findings database. Use when the user asks to "label", "tag", "categorize" or "run the decision model over" transcripts, or wants correction rates, task kinds or claimed outcomes across sessions. Optional; skips cleanly when no decision model is configured.
tags: [observability]
---

# transcript-decide

A decision model reads a short text and answers typed questions with probabilities. It is
fast and cheap, and it is only good at questions the text answers outright — it was measured
failing at nuanced judgments like severity or "was this claim verified". So this skill asks
shallow questions over small states, and code combines the answers. It never reads tool
results, and nothing else in this module needs it.

## Is a decision model configured?

The script reads `DECISION_URL`: the base URL of a gateway that routes a request with
`"model": "decision-default"` to a vllm-srun decision model's `/v1/systemone`. If it is unset
the script prints so and exits 0 — report that this skill is not set up and stop. Do not try
to find or guess a URL.

## Run a battery

```bash
uv run --script ./decide.py run --battery turn
uv run --script ./decide.py run --battery session
```

- `turn` asks one state per human turn in main sessions: the turn plus the end of the agent
  message before it. Questions: `intent` (new_task, follow_up, correction, approval,
  answers_agent, asks_question, other), `corrects_agent`, `frustration`, `grants_permission`.
- `session` asks one state per session: its first request and its final report. Questions:
  `claimed_outcome` (completed, partial, blocked, asks_user, unclear), `claims_tests_passed`,
  `claims_shipped`, `lists_open_items`, `task_kind`, `touches_live_systems`.

Narrow with `--since <ISO8601>`, `--limit N` (newest first) and `--reviewed` (only sessions
the transcript-review skill labelled). A run asks only what is not yet answered, so it resumes
after an interruption and an incremental run is cheap. A whole history takes hours on a shared
card; start with `--since` or `--limit` unless the user asked for everything.

If the index is missing, run the `transcript-ingest` skill first. An HTTP error other than
busy or loading stops the run with the server's message; report it. Rows already stored stay.

## Read the results

```bash
uv run --script ./decide.py rollup --battery turn
uv run --script ./decide.py calibrate --battery turn
```

`rollup` shows how each question's answers split. A yes/no answer between 0.2 and 0.8 is
`unsure`: the model sat near a coin flip, which is no decision — never read 0.7 as "probably".

`calibrate --battery turn` compares `corrects_agent` with transcript-review's `user_correction`
labels at several thresholds. Those labels are model output too, and on this history they were
the noisier side (they count tool denials and new requirements as corrections), so treat it as
agreement, not truth. No review category means a claimed outcome, so `session` has no calibration
signal. Check a threshold against hand-labelled examples before relying on it, and recalibrate
whenever a battery changes.

Measured on hand labels when these batteries shipped: `corrects_agent` was right 0.60 of the time
at 0.8 and 0.75 at 0.95 (40 turns). It also fires on reported failures, new constraints and the
user changing their own mind, so use it to order turns for review, with 0.95 as the cut, never
as a count of corrections. On 30 sessions `claimed_outcome` agreed 27 times and
`claims_tests_passed` at 0.8 caught 8 of 10 with 2 false alarms.

For anything else, query `decision_answers` in `findings.db` with the transcript-query skill's
tools: one row per question per unit, `value` is P(yes) for a yes/no question and the
confidence for a choice, `label` is the chosen option and `probabilities` the full split.

## Rules

- **A battery is one fixed unit.** On these requests every question sees the others, so
  editing, adding or reordering a question moves every answer in the battery. The script
  stores a hash of the battery with each answer; a changed battery starts from zero and its
  thresholds must be calibrated again.
- **Answers rank and label; they never exclude.** Do not use them to skip sessions from
  review — that was measured to miss real findings.
- **Do not open raw transcripts** or print states in bulk; this is the user's private history.
- **Read-only on the index**; writes only `findings.db`, which stays on the device.

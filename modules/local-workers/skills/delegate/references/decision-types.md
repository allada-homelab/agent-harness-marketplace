# Decision model reference (d3-ultra-INT4 via `decide`)

The model reads a **record** (`state`) once and answers **typed questions** about it, branching every
question from that one read, and returns a probability for every option. It is a classifier, not a chat model: it cannot
explain, count beyond its options, or say "I don't know" — uncertainty shows up only in the numbers
and flags below. Responses here are real, captured 2026-11-05 from `decision-default`.

## The three question types

| Type | Asks | `criteria` | Answer fields |
|---|---|---|---|
| `choice` | Pick one of named options | Object `{option: description}`; 2–255 options; a `null` description uses the option name | `choice`, `probabilities` per option, `confidence` |
| `noul` | Probability that a statement is true | Optional object `{"true": desc, "false": desc}` (or `yes`/`no`) | `noul` = P(true); with `threshold`, also `decision` (bool) |
| `score` | A level on an ordered scale | Ordered array of 2–10 level descriptions, lowest first | `score` (expected level, 0..n−1), `legend`, `probabilities`, `confidence` |

`type` is required by the tool.
`confidence` is the normalized top probability: 0 = uniform, 1 = certain. Ties go to the first option.

### choice — pick one

```json
{"type": "choice", "instructions": ["Route the ticket.", "Payments owns checkout; Web owns page rendering."],
 "criteria": {"payments": "Payments team", "web": "Web team", "infra": "Infrastructure"}}
```
→ `{"type": "choice", "choice": "payments", "probabilities": {"payments": 1.0, "web": 0.0, "infra": 0.0}, "confidence": 1.0}`

Write option descriptions that are mutually exclusive and cover the space; add an explicit
`"none": "None of the above"` option when "none" is possible, or the model must pick something.

### noul — yes/no as a probability

```json
{"type": "noul", "instructions": "Customers cannot complete purchases.",
 "criteria": {"true": "purchases blocked", "false": "purchases work"}, "threshold": 0.9}
```
→ `{"type": "noul", "noul": 1.0, "threshold": 0.9, "decision": true}`

Phrase `instructions` as a **statement** to be judged true or false. No `confidence` field: use the
value and the `floored` flag. `threshold`/`decision` is computed by the tool, not the model.

**Near coin flips.** Any yes/no with P between 0.199 and 0.801 is marked `"floored": true` (the name
comes from the earlier H2O model, which clamped those values to exactly 0.199/0.801). Real example —
a statement the record cannot support:

```json
{"type": "noul", "instructions": "The reporter is left-handed.", "threshold": 0.5}
```
→ `{"type": "noul", "noul": 0.486, "threshold": 0.5, "decision": false, "floored": true}`

That is **not** "no": the record does not say. A `choice` with a `"not_stated"` option does not rescue
it either — the same record split `yes` 0.513 / `not_stated` 0.487 and came back `low_confidence`.

### score — ordinal level

```json
{"type": "score", "instructions": "How urgent is this ticket?", "criteria": ["Low", "Medium", "High"]}
```
→ `{"type": "score", "score": 2.0, "legend": {"0": "Low", "1": "Medium", "2": "High"}, "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0}, "confidence": 1.0}`

`score` is an expected value (1.5 would sit between Medium and High); report the most probable level
from `probabilities` unless a continuous value is what the user wants.

## The record (`state`)

- A string is sent verbatim; any JSON value is sent as compact JSON. Prefer labelled JSON fields
  over prose when the record has structure.
- `instructions` may be a string, an object or an array (lines); empty → "Answer the question below."
- **~22K limit.** A question's prompt (the record plus that question) over 22,528 tokens is rejected,
  not cut: the item comes back `status: invalid` with `max_length_exceeded`. That is the GPU's
  memory, not the model's. Extract the relevant part first (`pi-run` can do this), or split the record.

## Images

Up to 4 per item: data URIs anywhere inside `state` (string, object value or list item), and/or a
top-level `images` list (data URI, bare base64, or http(s) URL the server can fetch). Each image in
`state` is replaced by `[image N]`, so the record can refer to it; `images` entries are numbered
first. Larger images are resized to at most ~1.6 MP.

## Batching

- One `decide` call, all records, ≤ 128 questions in total; split larger jobs into several calls.
- Put all questions about one record in **one item**: the record is read once for all of them.
  Cost grows with questions: ~170 ms for 1, ~670 ms for 16, ~2.3 s for 64 on a short record.
- Items run 8 at a time; one bad item never fails the others.

## Result flags → what to do

| Flag | Meaning | Do |
|---|---|---|
| `floored: true` (noul) | Near coin flip (P between 0.199 and 0.801) | No decision — decide yourself or report undecided |
| `low_confidence: true` (choice/score, confidence < 0.5) | Spread-out probabilities | No decision |
| `possibly_truncated: true` (item) | Only from the older H2O server: middle of the record dropped | Redo with a shorter record |
| `status: invalid` | Question malformed or record too long (exact reason in `error`) | Fix the question and resend that item |
| `status: error` | Model or network failure | Report it; do not silently substitute |

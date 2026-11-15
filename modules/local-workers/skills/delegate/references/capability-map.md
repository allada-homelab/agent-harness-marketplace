# What pi-run is suited for

Which task archetypes are safe to hand to the local model, which need a hard gate, and which stay
with you. pi-run runs `large-default:agent` (thinking on); the ratings are for that tier. They come
from the local-llm plugin's evals and replays on this homelab (2026-06/07, on that era's large tier)
plus published benchmarks for the model families llama-swap serves. Re-check a rating with
`/local-workers:replay-eval` when the model behind `large-default` changes.

`Reliable` = delegate, light verification. `Marginal` = delegate only behind a hard gate (diff,
compile, exit code); escalate on doubt. `Avoid` = keep it — confidently wrong output is the risk.

| # | Task archetype | Rating | Failure mode to gate against |
|---|---|---|---|
| 1 | Code search / navigation (grep, find usages, list) | Reliable | On an empty result it **invents a plausible path or symbol**. Require pasted tool output. |
| 2 | Read-then-extract | Reliable | Extrapolates fields that are not there. Pin it to "quote the line and its line number". |
| 3 | Mechanical edits / codemods | Reliable | Misses occurrences on large sweeps and "improves" adjacent code. Give the explicit file list; gate on the diff and a compile. |
| 4 | Test generation from a spec | Reliable | Writes the **minimum** test for the headline requirement (1 where a careful human wrote 6). Name every case you want; gate on the tests running. |
| 5 | Summarization | Reliable | Drops the one load-bearing detail; lost-in-the-middle on long input. Keep inputs short or chunked. |
| 6 | Classification at volume | Reliable | Label drift on ambiguous items. For a fixed question over many records, `decide` is the better worker. |
| 7 | Run commands, report output | Reliable | Paraphrases output and can misreport exit codes. Make it paste raw output and `$?`. |
| 8 | Structured / JSON output | Marginal | Malformed or truncated JSON. Ask for plain lines; validate any JSON and allow one retry. |
| 9 | Multi-step coding from a spec | Marginal→Reliable | Good **if the spec is airtight**; underspecified, it invents requirements. |
| 10 | Debugging unfamiliar failures | Avoid | Promotes a root cause from one sample; fixes by pattern-matching. |
| 11 | Architecture / design / tradeoffs | Avoid | Confident, generic, unjustified designs. |
| 12 | Long context (many large files) | Marginal | Retrieval rots in the middle even when it fits. Curate the excerpt; delegate the bounded extract. |

## The spec is the discriminator, not the file count

A multi-file change whose design you have already decided and gated is reliable; the file span is
not what breaks a local model, unresolved design is. Observed 2026-07-09: a subtle two-file
exception-recovery fix landed unaided and matched the human PR, because the orchestrator settled
the approach and a failing test gated it. So on a hard task, make the design call, set the gate,
then delegate — don't reach for a bigger model.

## Cross-cutting failure modes — these gate everything

1. **Described instead of done.** The model sometimes describes a tool call in prose and answers
   from memory. Check that the work happened: pasted output, a real diff.
2. **Fabricated outcome.** The closing summary can be unrelated to the work, or a confident fake
   success: one run reported "52 passed, the fix is already in commit X" over an empty diff with
   the bug still present (2026-07-09). Grade only the artifact you inspect.
3. **Hallucinated paths and APIs**, mostly after an empty search. Spot-check every specific name.
4. **Scope drift.** It "improves" adjacent code. Keep briefs single-objective with an explicit
   "do not touch X" line.
5. **No blast-radius reasoning.** A correct primary fix can break a pre-existing test or a caller
   the model never considered. Gate the changed module's suite and its direct consumers yourself.
6. **Stray artifacts.** Unrelated untracked files can appear. Check `git status` before trusting the
   diff.
7. **Passes its own tests, fails the repo's gates.** Strict type checks, linters and spell-check
   catch what its own pytest run does not. Put the project's real gate in the Verify line; expect
   one self-correction round.

## Using this when triaging

1. In an **Avoid** row? Keep it. An opt-in doesn't change that — delegate only its bounded
   sub-steps (search, extract, measure).
2. Otherwise delegate, and copy the row's failure mode into the brief's Verify line. For a local
   model that is the single highest-leverage line.

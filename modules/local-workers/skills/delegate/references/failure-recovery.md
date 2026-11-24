# Failure recovery: when a pi-run goes wrong

A local model fails differently from you: confidently wrong rather than confused, quicker to invent a
path or a function, and prone to wander when the brief is loose. Read this when a result looks off,
pi reports it is stuck, or you are deciding whether to re-brief or take the work back.

## Decision tree

```
pi-run returned.
├── Exit 0, artifact checks pass             → use it; synthesize for David.
├── Exit 0, smell test fails (below)         → verify first; a failed check is a failure mode below.
├── BLOCKED / "I need more information"      → never re-send the same brief:
│     ├── a gap you can fill (path, format, file list) → re-brief once with it;
│     └── a judgement call                              → take it back.
├── Confidently wrong                        → take it back. A local model can't be coached out of
│                                              an error it doesn't know it made.
├── Exit 124 (timeout)                       → check the artifact (an edit may be half-applied), then
│                                              continue ONCE with `pi-run --session <id>` and a
│                                              "continue where you stopped" brief. Still failing →
│                                              split it, or take it back.
├── Exit 2 (usage error or busy session)     → your bug, or a session already running: fix the call,
│                                              or `--fork` instead of `--session`.
└── Other non-zero / connection error        → the backend is down or the model errored: say so once,
                                               never loop on retries.
```

## Failure modes

- **Hallucinated files or symbols.** Spot-check every specific name with `Read` or `Grep`. If one is
  invented, take the work back; for a search, re-run with an explicit file list or search yourself.
- **Confidently wrong reasoning.** The piece was reason-out and should not have gone out. Don't relay
  it; redo it yourself and tell David the local result was unreliable.
- **Scope expansion.** A docstring request came back as a refactor. Reject it (`git checkout` the
  files and remove untracked strays) and re-brief with an explicit "change nothing else".
- **Stopped short.** It did 5 of 25 files. Split into parallel runs over explicit file lists
  (3 × 8 beats 1 × 25), each a disjoint set.
- **Wrong format.** Re-brief with the format as the literal last line: "Output exactly: <example>".
- **Silent regression.** It reported success; an unrelated test now fails. Every edit brief must
  carry a Verify command. If it ran the check, saw the failure and shipped anyway, take the work back.
- **Fabricated success.** It claims tests passed, yet the diff is empty or the bug remains. Only the
  artifact counts; see `capability-map.md`.

## Smell test

- Does it name specific files or symbols? Check at least one exists.
- Does it claim a check passed? Re-run it yourself for anything that matters.
- Suspiciously short ("Done!") or long (200 lines for a 5-line task)?
- Vague references ("the auth module") instead of paths?
- "You may also want to…" means it punted a decision: that part is unfinished.

A failed smell test doesn't mean the result is wrong — it means verify before passing it on.

## Re-brief or take it back

| Situation | Action |
|---|---|
| Brief was unclear; pi reported stuck | Re-brief once with the missing context |
| Brief was clear; it failed once | Take it back |
| The piece turned out to be reason-out | Take it back, even if pi produced something |
| Verification failed | Take it back; redo the change from a clean tree |
| Right content, wrong format | Re-brief with the exact format |
| Right content, missed files | Re-brief with the explicit list, or parallel runs for the rest |
| Failed twice | Take it back; don't try a third time |

When unsure, take it back: a local run that failed once on a clear brief rarely succeeds on a
marginal second try.

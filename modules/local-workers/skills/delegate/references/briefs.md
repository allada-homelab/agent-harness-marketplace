# Briefs: how to write a pi-run brief

pi starts with none of your context, and a local model follows a tight brief far better than a loose
one. Every brief answers the five questions in the skill (What, Where, How, Done, Verify) and ends
with the push-back line. If you cannot answer all five, the piece is probably reason-out: keep it.

The Verify line is the highest-leverage line in the brief. For edits, use the **project's own gate**
(`just lint && just typecheck && pytest tests/test_x.py`), not just a test run: a local model passes
its own pytest and then trips strict type checks or spell-check. Scope the test part to the affected
files so the run finishes in time; the wider regression gate is yours to run afterwards.

## Reading (`pi-run --read-only`)

End every reading brief with "Output ONLY the final result as `<format>` — no working, no
intermediate values, no commentary." A thinking model may otherwise print a provisional count, then
correct it, and the first number is the wrong one. When a number is load-bearing, cross-check it with
a cheap `grep -c` yourself.

```text
Task: Find every place in <scope> that calls/imports/references <symbol>.
Scope: <paths>
Output ONLY the final list of file:line per occurrence, grouped by file — no commentary.
If there are none, write NONE. Never name a file you did not see in tool output.
```

```text
Task: Read <files> and summarize <what> in <length>.
Cite file:line for each claim. If the files don't say, write UNKNOWN — do not guess.
Output ONLY the summary, as <format>.
```

## Edits (`pi-run`)

```text
Task: <transformation> in each of these files: <explicit list>.
Pattern: follow <example file>, or: before `<old>` → after `<new>`.
Do NOT change anything else, and do not edit <migrations/, *.lock, generated/ …>.
Verify: run `<gate command>` and paste its last 20 lines and exit code.
If you cannot do this exactly as specified, reply `BLOCKED: <reason>` instead.
Output: each file changed, with the lines changed.
```

## Commands (`pi-run`)

```text
Task: For each of <items>, run `<command using {item}>` (60 s limit each).
Output: a table — item, exit code, one-line result — then the raw stderr of every failure.
Report the exit code you saw; never infer success from the output's wording.
```

## Spec-driven coding (`pi-run`, usually in the background)

```text
Task: Implement <feature>.
Spec:
- Create <file> with <function>(<params>) -> <return> that <behaviour>.
- Handle <edge cases>.
Pattern: follow <reference file>.
Tests: at <path>, one test each for: <case 1>, <case 2>, <error path>, <boundary> …
Done when the tests pass and `<gate command>` exits 0.
If anything in the spec is unclear, reply `BLOCKED: <question>` instead of guessing.
Output: files created or changed, and the gate's exit code.
```

Name every test case you want. Left to "write tests", the model writes the one test that satisfies
the headline requirement and stops.

## Anti-patterns

- **"Figure out the best way to X."** It picks *a* way and presents it confidently. Choose the
  approach yourself, then delegate the implementation.
- **Pasting a whole file into the brief.** It has tools; point at the file.
- **"Also, while you're at it…"** One objective per run; send a second run instead.
- **"Make sure it's correct."** Meaningless. Say how to check: a command and its expected exit code.
- **No "done when".** The run doesn't know when to stop: you get too much work or too little.
- **Asking for a review or feedback.** Review is reason-out; you get a generic checklist. Delegate
  specific mechanical checks instead.

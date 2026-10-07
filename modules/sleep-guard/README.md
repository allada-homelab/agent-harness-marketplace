# sleep-guard

A `PreToolUse` hook on `Bash`. It blocks a command that opens — after any leading
`cd <dir> &&` — with a foreground `sleep N` of 5 seconds or more
(`sleep 60 && kubectl get pods`, `cd app && sleep 30; curl …`, a bare `sleep 90`). A fixed wait holds the turn for the full duration and still guesses
at timing. The block reason points the agent at a condition wait that returns as
soon as the thing is ready:

```
timeout 300 bash -c 'until <check>; do sleep 5; done'
```

or at the harness's background mechanism (on dsh: `bash` with
`run_in_background`, then `job_output`).

Allowed: sleeps under 5s (settle delays), `sleep N &`, calls made with
`run_in_background` (dsh's hook runner must pass that flag through — see the
hook contract's `Bash` input shape), and any `sleep` that is not the first command (an
`until … sleep` loop, `cmd; sleep 2; cmd`).

**Claude Code blocks this pattern natively**, so enable this module on pi and dsh
only; on Claude it would only repeat the built-in refusal.

## Install

- pi and dsh: enable the module; the harness hook runner discovers
  `hooks/hooks.json` in every installed module.

## Test

`bin/check.sh` runs `test/test_sleep_guard.py`.

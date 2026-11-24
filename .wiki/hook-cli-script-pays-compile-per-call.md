---
type: gotcha
title: Hook running a large CLI as a script pays compile and argparse per call
description: "Module hook adds about 60 ms per tool call when bin/ is a big Python script: it recompiles and rebuilds argparse each run. Keep bin a shim that imports the CLI, and dispatch hook early."
tags: [performance, modules]
generated: {by: okf-wiki/unknown, at: 2026-11-15T17:05:42Z}
verified:
  - {by: okf-wiki/unknown, at: 2026-11-15T17:05:42Z, commit: 265590d8ade8}
sources:
  - {id: measure-2026-11-15, resource: local measurement 2026-11-15 of switchboard 0.7.0 vs 0.7.1 hook; Python 3.14 on Linux; one cold process per run; medians}
  - {id: switchboard-0.7.1, resource: "switchboard 0.7.1 fix: modules/switchboard/bin/switchboard is a shim over modules/switchboard/skills/switchboard/switchboard.py"}
---

# Hook running a large CLI as a script pays compile and argparse per call

## Symptom

A per-tool PostToolUse hook for switchboard 0.7.0 took about 75 ms per call. The 11 ms interpreter floor and the hook's own work (one heartbeat UPDATE plus a few SELECTs, about 6 ms) account for little of that [^measure-2026-11-15].

## What fails

Python writes `__pycache__` only for imported modules, never for the script it runs as. So `bin/switchboard` (1,350 lines) was recompiled on every call, about 25 ms [^measure-2026-11-15]. Then `main()` built the whole argparse tree (39 parsers) before dispatching `hook`. On Python 3.14 each parser construction probes gettext and colour support, about 1 ms each cold, another roughly 25 ms [^measure-2026-11-15].

A first diagnosis blamed SQLite. That was an artefact of reusing connections in one process, plus fsync spikes on a loaded host. The same UPDATE on a fresh connection takes about 6 ms [^measure-2026-11-15].

## What works

Keep `bin/` a thin shim that imports the CLI, so the CLI is cached as a module. `main()` dispatches `hook <event>` before `import argparse`, and `subprocess`/`shutil` are imported inside the functions that use them [^switchboard-0.7.1]. Measured: about 36 ms per hook, or about 61 ms where the install is read-only and no bytecode can be written [^measure-2026-11-15].

Measure a hook cold, one process per run, interleave old and new, and compare medians. Host load moves absolute numbers by about 2x.

## Why

Bytecode caching applies only to imports. Argparse construction cost scales with the number of parsers, and it runs before dispatch unless the hook path returns first.

Not done on purpose: `PRAGMA synchronous=NORMAL` (no gain, 5.7 vs 5.2 ms, because closing the last connection checkpoints anyway). Narrowing the PostToolUse matcher was also rejected, because it would delay feed delivery and the lease heartbeat on read-only tools [^measure-2026-11-15].

## Verify

- `modules/switchboard/bin/switchboard` :: `from switchboard import main`

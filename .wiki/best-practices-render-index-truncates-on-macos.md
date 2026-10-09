---
type: gotcha
title: best-practices render-index.sh truncates INDEX.md on macOS
description: render-index.sh calls GNU realpath --relative-to, so on macOS it aborts mid-run and truncates INDEX.md; check the INDEX.md diff after every render.
tags: [paths, skills]
generated: {by: okf-wiki/haiku, at: 2026-10-09T14:43:46Z}
verified:
  - {by: okf-wiki/haiku, at: 2026-10-09T14:43:46Z, commit: ef1bd15891ec}
sources:
  - {resource: modules/best-practices/tools/render-index.sh, line: 109, id: render-index}
---

# best-practices render-index.sh truncates INDEX.md on macOS

## Symptom

Running `modules/best-practices/tools/render-index.sh` on macOS prints `realpath: illegal option -- -` and `INDEX.md` loses 418 lines (observed 2026-10-09). The error is easy to miss when the script is chained before `tools/lint.sh`.

## What fails

The script calls `realpath --relative-to` [^render-index] on the branch taken when a rule has no `references/<topic>.md` and must search `references/` for its anchor. macOS ships BSD `realpath`, which rejects the flag. `set -euo pipefail` aborts the run after the header has already been written, leaving `INDEX.md` truncated. `tools/lint.sh` uses the same flag only on its dead-link error path, so it passes on macOS unless a dead link exists.

## What works

Run it on Linux or install GNU coreutils. A workaround that produced a correct, additions-only `INDEX.md`: a scratch `realpath` shim placed first on `PATH` that implements `--relative-to=BASE PATH` with `python3 os.path.relpath(os.path.realpath(PATH), os.path.realpath(BASE))`. Keep the shim outside the repo.

## Why

The script was written against GNU coreutils, and BSD `realpath` has no `--relative-to`. The only signal is the stderr line, so a truncated file can pass unnoticed. This is the same class of failure as `check-sh-fails-on-macos-without-timeout`, another GNU-only tool assumption on macOS.

## Verify

- `modules/best-practices/tools/render-index.sh` :: `realpath --relative-to`

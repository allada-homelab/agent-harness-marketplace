---
type: gotcha
title: bin/check.sh fails on macOS without timeout binary
description: bin/check.sh test suite fails on macOS hosts lacking timeout/gtimeout, though the fallback path passes; check assumes timeout exists to assert the fallback is reachable.
tags: [check-sh]
generated: {by: okf-wiki/haiku, at: 2026-10-05T15:44:11Z}
verified:
  - {by: okf-wiki/haiku, at: 2026-10-05T15:44:11Z, commit: 362cf7244be5}
sources:
  - {resource: modules/dual-agent-pr-review/test/timeout_portability.sh, line: 63, id: test-check}
---

# bin/check.sh fails on macOS without timeout binary

## Symptom

Running `bin/check.sh` on a macOS host without `timeout` or `gtimeout` installed (from GNU coreutils) exits with a test failure: "FAIL: sandbox PATH still resolves timeout" (1 failed, 480 passed).

## What fails

The test_timeout_portability_suite check in `modules/dual-agent-pr-review/test/timeout_portability.sh` [^test-check] is designed to verify that `dual_review.sh`'s `run_with_timeout()` fallback works when the host lacks a native `timeout` binary. The test at line 63–65 checks `command -v timeout >/dev/null && [[ ! -e "$BIN/timeout" ]]`, passing only if the host has `timeout` AND the sandbox doesn't—asserting the fallback branch is reachable. On a Mac where `timeout` is absent entirely, the first condition fails and the assertion fails, even though the fallback itself works correctly.

## What works

Every other check in the suite passes on such a host, including the four fallback cases that run `run_with_timeout` under a stripped PATH (fast exit, propagated non-zero exit, overrun → 124 in 10 of 10 trials, children killed with it). CI's `check` job on ubuntu, which has `timeout`, passes. Treat this as a known baseline failure when reporting the local gate, not as a regression.

## Why

The check exists to prove the fallback branch is actually reachable: the host must *have* `timeout` and the sandbox must not. Stock macOS has no `timeout`. Homebrew coreutils installs it as `gtimeout`, which this check does not look for, so `brew install coreutils` alone likely does not clear it (inferred, not run); putting coreutils' `gnubin` directory on PATH should.

## Verify

- `modules/dual-agent-pr-review/test/timeout_portability.sh` :: `sandbox PATH still resolves timeout`

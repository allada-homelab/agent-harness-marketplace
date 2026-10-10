---
type: gotcha
title: Chrome's IsolateSandboxedIframes silences deferred errors in headless probes
description: Chrome's sandboxed iframe isolation (`IsolateSandboxedIframes`) blocks `--virtual-time-budget`, silencing deferred errors; fix with `--disable-features=IsolateSandboxedIframes`.
tags: [testing, chrome]
generated: {by: okf-wiki/haiku, at: 2026-10-07T18:59:50Z}
verified:
  - {by: okf-wiki/haiku, at: 2026-10-07T18:59:50Z, commit: a29cb7b9182b}
  - {by: okf-wiki/haiku, at: 2026-10-10T03:34:46Z, commit: 41c5f19df087}
sources:
  - {id: s1, resource: modules/artifacts/skills/artifacts/artifactctl.py, note: "render(): sandbox command-line branch and deferred-error live tests in test_artifactctl.py"}
---

# Chrome's IsolateSandboxedIframes silences deferred errors in headless probes

## Symptom

A headless Chrome probe passes `--virtual-time-budget` to run fast tests, and expects errors thrown inside sandboxed iframes to be reported via console output. The frame contains a timer (`setTimeout(() => { throw new Error(...) }, delay)`) that should fire during the budget window, but the error is silently missed. The error is silently missed even though timers on the host page fire correctly.

## What fails

Running a headless Chrome probe with `--virtual-time-budget` on a page with a sandboxed iframe (e.g., `sandbox="allow-scripts"` srcdoc):

```
chrome --headless --dump-dom --virtual-time-budget=3500 page-with-sandboxed-frame.html
```

The sandboxed iframe's timers (1000 ms, 2500 ms, 3800 ms) never fire. Errors thrown from `setTimeout` inside the frame produce no console output — the probe reports `ok` even though the frame should have thrown.

## What works

Pass `--disable-features=IsolateSandboxedIframes` to Chrome:

```
chrome --headless --dump-dom --virtual-time-budget=3500 \
  --disable-features=IsolateSandboxedIframes page-with-sandboxed-frame.html
```

The frame's timers now fire during the virtual time budget. Errors thrown from the frame's `setTimeout` callbacks are reported to console. Sandbox restrictions remain in effect: form submission still throws, and storage access is blocked (the flag only disables process isolation, not sandbox semantics).

Alternative: `--disable-site-isolation-trials` also works but is broader. Prefer the granular `IsolateSandboxedIframes` flag for precision.

## Why

Chrome 154+ introduced the `IsolateSandboxedIframes` feature (enabled by default in headless mode): sandboxed iframes run in their own isolated process to improve security. However, `--virtual-time-budget` only advances time in the browser's main process. The isolated iframe process receives no virtual-time ticks, so its event loop never progresses—timers fire nowhere. The main page's timers continue advancing normally because they share the browser process.

One red herring: an initial hypothesis suggested `--dump-dom` exits the browser before the budget window closes, but probe timing (0.4 s runtime for a 3.5 s budget) rules this out—the budget runs its full duration; the frame simply stays suspended.

## Verify

- `modules/artifacts/skills/artifacts/artifactctl.py` :: `IsolateSandboxedIframes`

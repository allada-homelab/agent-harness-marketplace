#!/usr/bin/env python3
"""PreToolUse: block a Bash call that opens (after any `cd`) with a foreground `sleep N` (N >= 5 s) —
a fixed polling wait that holds the turn and still guesses at timing — and point the
model at a condition wait or the harness's background mechanism. Exit 2 blocks with
the reason on stderr; every other path (including bad stdin) exits 0.
Claude Code blocks this pattern natively; the hook is for pi and dsh."""
import json
import re
import sys

THRESHOLD = 5  # seconds; shorter sleeps are settle delays (a port opening, a file flushing), not polling
# A leading `cd <dir> &&` (or `;`) chain is skipped: agents prefix their polls with it as often as not.
SLEEP = re.compile(r"^\s*(?:cd\s+(?:\"[^\"]*\"|'[^']*'|\S+)\s*(?:&&|;)\s*)*sleep\s+(\d+(?:\.\d+)?)([smhd]?)(?=[\s;&|]|$)")
UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def reason(ev):
    if ev.get("tool_name") != "Bash":
        return None
    ti = ev.get("tool_input") or {}
    if ti.get("run_in_background"):
        return None
    m = SLEEP.match(ti.get("command") or "")
    if not m:
        return None
    rest = ti["command"][m.end():].lstrip()
    if rest.startswith("&") and not rest.startswith("&&"):
        return None  # `sleep N &` is already backgrounded
    secs = float(m.group(1)) * UNITS[m.group(2)]
    if secs < THRESHOLD:
        return None
    return (f"sleep-guard: blocked a foreground `sleep {m.group(1)}{m.group(2)}`. A fixed wait holds the "
            "whole turn and still guesses at timing. Wait on the condition instead, so it returns the "
            "moment the thing is ready:\n"
            "  timeout 300 bash -c 'until <check>; do sleep 5; done'\n"
            "or start the long-running work in the background and read its output later (on dsh: bash "
            "with run_in_background, then job_output). Fixed delays under 5s are allowed.")


def main():
    try:
        msg = reason(json.load(sys.stdin))
    except Exception:
        return 0  # fail open: a malformed event must never block the shell
    if msg:
        print(msg, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

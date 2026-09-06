#!/usr/bin/env python3
"""STAND-IN for the author's private reflect-on-done.py Stop hook, used only so
modules/claude-transcripts' tests can exercise analyze.py's hooks-replay lens
in CI without the real hook installed. Implements only the interface
analyze.py needs (analyze(path, final_text)) with the smallest logic that
satisfies the test suite — it is NOT a port of the real hook's rules.
"""

import json
import re

COMMIT_RE = re.compile(r"\bgit\s+commit\b")
STATUS_ICON_RE = re.compile(r"[✅❌⚠️]")


def analyze(path, final_text):
    """Return True if the turn closes work (e.g. a commit) without a
    status-line close (a ✅/❌/⚠️ marker) in `final_text`."""
    closing = False
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            content = entry.get("message", {}).get("content")
            if isinstance(content, list):
                for b in content:
                    if b.get("type") == "tool_use" and b.get("name") == "Bash":
                        cmd = str(b.get("input", {}).get("command", ""))
                        if COMMIT_RE.search(cmd):
                            closing = True
    if not closing:
        return False
    return not STATUS_ICON_RE.search(final_text or "")

#!/usr/bin/env python3
"""STAND-IN for the author's private verify-claims.py Stop hook, used only so
modules/claude-transcripts' tests can exercise analyze.py's hooks-replay lens
in CI without the real hook installed. Implements only the interface
analyze.py needs (CLAIM_RE, analyze(path, final_text)) with the smallest logic
that satisfies the test suite — it is NOT a port of the real hook's rules.
"""

import json
import re

# A completion claim: "I ran/tested/verified/checked/confirmed ... it works/passes".
CLAIM_RE = re.compile(
    r"\b(?:ran|tested|verified|checked|confirmed)\b[^.\n]*"
    r"\b(?:pass(?:es|ed)?|works?|working|succeed(?:s|ed)?)\b",
    re.IGNORECASE,
)


def analyze(path, final_text):
    """Return the matched claim text if `final_text` makes an unverified
    completion claim (a claim with zero tool uses in the turn), else None."""
    claim = CLAIM_RE.search(final_text or "")
    if not claim:
        return None
    tool_uses = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            content = entry.get("message", {}).get("content")
            if isinstance(content, list):
                tool_uses += sum(1 for b in content if b.get("type") == "tool_use")
    if tool_uses:
        return None
    return claim.group(0).strip()

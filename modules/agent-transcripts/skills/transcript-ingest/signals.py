"""The per-session review rules ingest stores in `session_signals` and `review.py` renders with.

Stdlib only: `transcripts.py` and `review.py` both import it, and the review script declares
no dependencies. Bump SIGNALS_VERSION whenever a rule here changes (BOILERPLATE included: it
decides what counts as the user talking); the next ingest then recomputes every row from the
stored messages without re-parsing a file.
"""

from __future__ import annotations

import re

SIGNALS_VERSION = 1

SHORT_USER = 300  # a correction is a short turn; a long one is a new instruction

# Injected text that is not the user talking. Learned by reading the live index: on claude
# and dsh roughly half of all "user" characters are one of these. Each entry is
# (label, harness or "*", regex); a match is replaced by `[stripped: <label>]`.
# Block forms come first; the `.*` forms run to the end of the message, which is how the
# harness appends them. Tune here, not in the renderer.
BOILERPLATE = (
    ("system-reminder", "*", re.compile(r"<system-reminder>.*?</system-reminder>", re.S)),
    ("system-reminder", "*", re.compile(r"<system-reminder>.*", re.S)),  # truncated block
    ("task-notification", "claude",
     re.compile(r"<task-notification>.*?</task-notification>", re.S)),
    ("task-notification", "claude", re.compile(r"<task-notification>.*", re.S)),
    ("slash-command", "claude",
     re.compile(r"<command-(name|message|args)>.*?</command-\1>", re.S)),
    ("local-command-output", "claude",
     re.compile(r"<local-command-(stdout|stderr|caveat)>.*?</local-command-\1>", re.S)),
    ("skill-body", "claude", re.compile(r"^Base directory for this skill:.*", re.S | re.M)),
    ("hook-output", "claude", re.compile(
        r"^(?:Stop|SubagentStop|PreToolUse|PostToolUse|PreCompact|SessionStart|SessionEnd|"
        r"UserPromptSubmit|Notification)\s+hook\s+(?:feedback|error|success|output|blocked)\b.*",
        re.S | re.M)),
    ("background-task", "claude",
     re.compile(r"^\[SYSTEM NOTIFICATION - NOT USER INPUT\].*", re.S | re.M)),
    ("compact-summary", "claude",
     re.compile(r"^This session is being continued from a previous conversation.*", re.S | re.M)),
    ("runtime-context", "dsh", re.compile(r"^Current runtime context\..*", re.S | re.M)),
    ("checkpoint", "dsh",
     re.compile(r"^This is an automatically generated checkpoint.*", re.S | re.M)),
    ("background-subagent", "dsh",
     re.compile(r"^Background subagent \S+ (?:finished|reported)\b.*", re.S | re.M)),
    ("background-job", "dsh", re.compile(r"^background job \S+ .*", re.S | re.M)),
    ("goal-blocked", "dsh", re.compile(r"<goal_blocked>.*?</goal_blocked>", re.S)),
)

# A short user turn that matches this is the user pulling the reins.
CORRECTION_RE = re.compile(
    r"\bno,|\bstop\b|\bwrong\b|\bagain\b|\bI said\b|\bdon['’]t\b|\bundo\b|\brevert\b",
    re.I,
)


def human_text(text: str, harness: str) -> str:
    """What is left of a user turn once the harness's injected blocks are removed."""
    clean, _ = strip_boilerplate(text or "", harness)
    return re.sub(r"\[stripped: [^\]]+\]", "", clean).strip()


def strip_boilerplate(text: str, harness: str) -> tuple[str, int]:
    """Replace injected blocks with `[stripped: label]`. Returns (text, blocks stripped)."""
    stripped = 0
    for label, scope, pattern in BOILERPLATE:
        if scope not in ("*", harness):
            continue
        text, n = pattern.subn(f"[stripped: {label}]", text or "")
        stripped += n
    return text, stripped

#!/usr/bin/env python3
"""UserPromptSubmit detector for get-shit-done's (opt-in) auto-trigger.

DISABLED BY DEFAULT. This script ships wired to nothing — GSD is explicit-only
(`/get-shit-done-claude:run`) until you turn the auto-trigger on. To enable: copy
`hooks/auto-trigger.example.json` to `hooks/hooks.json` and run `/reload-plugins`.

When enabled, it scans each user prompt for complexity / fan-out signals and, on a
match, injects a one-line nudge suggesting `/get-shit-done-claude:run`. It only ever
*suggests* — a hook cannot invoke a skill, and this never blocks or edits anything.

Stdlib only. Conservative matcher — bias toward NOT firing, so a stray "build" in
casual chat doesn't nag. Tune SIGNALS to taste.
"""
import json
import re
import sys

# Multi-word / intent phrases that signal genuinely orchestration-worthy work.
# Deliberately narrow: single generic verbs ("fix", "add") are excluded on purpose.
SIGNALS = [
    r"\bfan[ -]?out\b",
    r"\bin parallel\b",
    r"\bmigrat(e|ion)\b.{0,40}\b(all|every|across|codebase|repo)\b",
    r"\brefactor\b.{0,40}\b(across|everywhere|all|codebase|repo)\b",
    r"\b(implement|build|design)\b.{0,60}\b(feature|system|pipeline|service|end[ -]to[ -]end)\b",
    r"\bmulti[ -]step\b",
    r"\bcomplex\b.{0,30}\b(task|change|feature|refactor|migration)\b",
    r"\bacross\b.{0,20}\b(files|modules|packages|services)\b",
]
_RE = re.compile("|".join(SIGNALS), re.IGNORECASE)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # fail open — never break prompt submission
    prompt = payload.get("prompt", "") or ""
    if not _RE.search(prompt):
        return 0
    nudge = (
        "[get-shit-done] This looks like complex or fan-out work. Consider "
        "`/get-shit-done-claude:run <task>` to decompose it, delegate subtasks by "
        "complexity (Sonnet/Opus), concurrent research, and adversarially "
        "verify before done."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": nudge,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Rewrite a Bash command: prefix it with an echo marker."""
import json, sys
event = json.load(sys.stdin)
cmd = event["tool_input"]["command"]
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
      "updatedInput": {"command": "echo rewritten; " + cmd}}}))

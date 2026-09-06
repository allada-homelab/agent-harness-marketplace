#!/usr/bin/env python3
"""Rewrite a Bash command: prefix it with an echo marker."""
import json, os, sys
event = json.load(sys.stdin)
_out = os.environ.get("HOOK_CONTRACT_ECHO")
if _out:
    with open(_out, "w") as _f:
        json.dump(event, _f)
cmd = event["tool_input"]["command"]
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
      "updatedInput": {"command": "echo rewritten; " + cmd}}}))

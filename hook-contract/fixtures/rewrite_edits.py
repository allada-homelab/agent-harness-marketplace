#!/usr/bin/env python3
"""Uppercase every replacement in a multi-edit Edit call and return the whole list."""
import json, os, sys
event = json.load(sys.stdin)
_out = os.environ.get("HOOK_CONTRACT_ECHO")
if _out:
    with open(_out, "w") as _f:
        json.dump(event, _f)
edits = [{"old_string": e["old_string"], "new_string": e["new_string"].upper()} for e in event["tool_input"]["edits"]]
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": {"edits": edits}}}))

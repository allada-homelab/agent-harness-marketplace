#!/usr/bin/env python3
"""Block via the exit-2 channel; stderr is the reason."""
import json, os, sys
event = json.load(sys.stdin)
_out = os.environ.get("HOOK_CONTRACT_ECHO")
if _out:
    with open(_out, "w") as _f:
        json.dump(event, _f)
print(f"denied by exit2 fixture: {event.get('tool_name')}", file=sys.stderr)
sys.exit(2)

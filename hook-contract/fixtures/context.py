#!/usr/bin/env python3
"""Inject additional context, echoing the event name so the test can see which seam fired."""
import json, os, sys
event = json.load(sys.stdin)
_out = os.environ.get("HOOK_CONTRACT_ECHO")
if _out:
    with open(_out, "w") as _f:
        json.dump(event, _f)
print(json.dumps({"hookSpecificOutput": {"hookEventName": event["hook_event_name"],
      "additionalContext": f"CONTEXT-FROM-{event['hook_event_name']}"}}))

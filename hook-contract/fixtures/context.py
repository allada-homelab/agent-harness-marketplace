#!/usr/bin/env python3
"""Inject additional context, echoing the event name so the test can see which seam fired."""
import json, sys
event = json.load(sys.stdin)
print(json.dumps({"hookSpecificOutput": {"hookEventName": event["hook_event_name"],
      "additionalContext": f"CONTEXT-FROM-{event['hook_event_name']}"}}))

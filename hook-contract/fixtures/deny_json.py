#!/usr/bin/env python3
"""Block via the stdout-JSON channel."""
import json, sys
json.load(sys.stdin)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
      "permissionDecision": "deny", "permissionDecisionReason": "denied by json fixture"}}))

#!/usr/bin/env python3
"""Force a follow-up at turn end, once (stop_hook_active guards the loop)."""
import json, sys
event = json.load(sys.stdin)
if event.get("stop_hook_active"):
    sys.exit(0)
print(json.dumps({"decision": "block", "reason": "stop fixture wants one more turn"}))

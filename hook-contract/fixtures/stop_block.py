#!/usr/bin/env python3
"""Force a follow-up at turn end, once (stop_hook_active guards the loop)."""
import json, os, sys
event = json.load(sys.stdin)
_out = os.environ.get("HOOK_CONTRACT_ECHO")
if _out:
    with open(_out, "w") as _f:
        json.dump(event, _f)
if event.get("stop_hook_active"):
    sys.exit(0)
print(json.dumps({"decision": "block", "reason": "stop fixture wants one more turn"}))

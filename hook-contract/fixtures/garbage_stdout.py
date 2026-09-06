#!/usr/bin/env python3
"""Exit 0 with non-JSON stdout: must be ignored, action proceeds unchanged."""
import json, os, sys
event = json.load(sys.stdin)
_out = os.environ.get("HOOK_CONTRACT_ECHO")
if _out:
    with open(_out, "w") as _f:
        json.dump(event, _f)
print("not json at all {")

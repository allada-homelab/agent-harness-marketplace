#!/usr/bin/env python3
"""Record the stdin event to $HOOK_CONTRACT_ECHO and proceed. Proves translation."""
import json, os, sys
event = json.load(sys.stdin)
out = os.environ.get("HOOK_CONTRACT_ECHO")
if out:
    with open(out, "w") as f:
        json.dump(event, f)
sys.exit(0)

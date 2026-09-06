#!/usr/bin/env python3
"""Block via the exit-2 channel; stderr is the reason."""
import json, sys
event = json.load(sys.stdin)
print(f"denied by exit2 fixture: {event.get('tool_name')}", file=sys.stderr)
sys.exit(2)

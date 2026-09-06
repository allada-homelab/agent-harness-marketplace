#!/usr/bin/env python3
"""Exit 0 with non-JSON stdout: must be ignored, action proceeds unchanged."""
import sys
sys.stdin.read()
print("not json at all {")

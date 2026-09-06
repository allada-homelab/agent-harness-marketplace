#!/usr/bin/env python3
"""Exit 1 with a traceback-ish stderr: the runner must fail open and loud."""
import sys
print("fixture crashed on purpose", file=sys.stderr)
sys.exit(1)

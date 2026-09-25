#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""okf-wiki: deterministic operations on the OKF v0.2 bundle at <repo>/.wiki/.

Stdlib only. Every verb ends with one stable line `okf: <verb> <verdict> [detail]`.
Exit codes: 0 ok, 1 findings (validate errors, broken anchors), 2 refusal or usage error,
3 near-duplicate refused by `new`. The two hook verbs always exit 0 (fail open, loud).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import groupby
from pathlib import Path

TYPES = ("gotcha", "decision", "runbook", "convention", "architecture", "reference")
KEY_ORDER = ("type", "resource", "title", "description", "tags", "status", "generated",
             "verified", "stale_after", "sources", "usage_window")
BUNDLE = ".wiki"
OKF_VERSION = "0.2"
SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$")
ACTOR_RE = re.compile(r"^(okf-wiki/[a-z0-9.-]+|human:\S+|process:\S+)$")
DESC_MAX = 200
WORDS_MAX = 400
VERIFIED_KEEP = 5
FANOUT_DEFAULT, FANOUT_MIN, FANOUT_MAX = 4, 1, 16
DIGEST_VERSION = 1
DIGEST_BUDGET = 8000  # characters, roughly 2k tokens
REFLECT_SESSIONS, REFLECT_DAYS = 20, 14
STATE_TTL_DAYS = 7


class OkfError(Exception):
    """A refusal: printed as `okf: <verb> refused <message>`, exit 2."""


def status(verb: str, verdict: str, detail: str = "") -> None:
    print(f"okf: {verb} {verdict}" + (f" {detail}" if detail else ""))


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_ts(s: str) -> datetime | None:
    if not TS_RE.match(s):
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def git(root: Path, *args: str, check: bool = True, timeout: float = 10) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                       timeout=timeout)
    if check and r.returncode:
        raise OkfError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def repo_root(start: Path) -> Path | None:
    try:
        out = git(start, "rev-parse", "--show-toplevel", timeout=5)
    except (OkfError, OSError, subprocess.TimeoutExpired):
        return None
    return Path(out.strip())


def resolve_fanout(flag: int | None) -> tuple[int, str]:
    if flag is not None:
        value, source = flag, "flag"
    elif os.environ.get("OKF_WIKI_FANOUT"):
        raw = os.environ["OKF_WIKI_FANOUT"]
        if not raw.strip().isdigit():
            raise OkfError(f"OKF_WIKI_FANOUT={raw!r} is not a whole number")
        value, source = int(raw), "env"
    else:
        return FANOUT_DEFAULT, "default"
    if not FANOUT_MIN <= value <= FANOUT_MAX:
        raise OkfError(f"fanout {value} ({source}) must be between {FANOUT_MIN} and {FANOUT_MAX}")
    return value, source


def _root_and_bundle(args, need_bundle: bool = True) -> tuple[Path, Path]:
    start = Path(args.root).resolve() if args.root else Path.cwd()
    root = repo_root(start) or start
    bundle = root / BUNDLE
    if need_bundle and not bundle.is_dir():
        raise OkfError(f"no {BUNDLE}/ at {root}")
    return root, bundle


def cmd_fanout(args) -> int:
    n, source = resolve_fanout(args.fanout)
    status("fanout", str(n), f"({source})")
    return 0


# ---- CLI ----------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="okf.py", description="okf-wiki: deterministic operations on <repo>/.wiki/")
    p.add_argument("--root", help="repository root (default: the git toplevel of the cwd)")
    sub = p.add_subparsers(dest="verb", required=True)

    def verb(name, fn, *positional, **flags):
        s = sub.add_parser(name)
        for a in positional:
            s.add_argument(a, **({"nargs": "*"} if a == "ids" else {}))
        for flag, kw in flags.items():
            s.add_argument(flag.replace("_", "-"), **kw)
        s.set_defaults(fn=fn)

    verb("fanout", cmd_fanout, __fanout={"type": int})
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except OkfError as e:
        print(f"okf: {args.verb} refused {e}", file=sys.stderr)
        status(args.verb, "refused", str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())

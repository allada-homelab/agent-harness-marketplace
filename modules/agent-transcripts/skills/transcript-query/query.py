#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Run one read-only query against the agent-transcripts index, with capped output.

The caps are the point. The index holds hundreds of megabytes of transcript prose, and a
single message can exceed a megabyte, so an uncapped `SELECT text ...` would empty private
conversations into whatever context is running the query. Every cell is truncated and every
result set is limited unless the caller raises the cap deliberately.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

DEFAULT_DEST_NAME = "agent-transcripts"


def resolve_dest(cli_dest: str | None) -> Path:
    """--dest > $AGENT_TRANSCRIPT_DIR > <user cache dir>/agent-transcripts."""
    if cli_dest:
        return Path(cli_dest).expanduser()
    if os.environ.get("AGENT_TRANSCRIPT_DIR"):
        return Path(os.environ["AGENT_TRANSCRIPT_DIR"]).expanduser()
    cache = os.environ.get("XDG_CACHE_HOME")
    root = Path(cache).expanduser() if cache else Path.home() / ".cache"
    return root / DEFAULT_DEST_NAME


def connect(dest_root: Path) -> sqlite3.Connection:
    """Read-only so a query can never lock or corrupt an index an ingest is writing."""
    db = dest_root / "transcripts.db"
    if not db.exists():
        raise SystemExit(f"no index at {db}; run the transcript-ingest skill first")
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def render(rows: list, headers: list[str], width: int) -> str:
    """One row per line, every cell truncated to `width` characters."""
    def cell(v):
        s = "" if v is None else str(v)
        s = s.replace("\n", "\\n").replace("\t", " ")
        return s if len(s) <= width else s[:width] + f"…(+{len(s) - width})"

    out = [" | ".join(headers)]
    out += [" | ".join(cell(v) for v in row) for row in rows]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sql", help="a single SELECT statement")
    ap.add_argument("params", nargs="*", help="values for ? placeholders")
    ap.add_argument("--dest")
    ap.add_argument("--limit", type=int, default=50, help="max rows printed (default 50)")
    ap.add_argument("--width", type=int, default=200, help="max chars per cell (default 200)")
    args = ap.parse_args(argv)

    conn = connect(resolve_dest(args.dest))
    cur = conn.execute(args.sql, tuple(args.params))
    rows = cur.fetchmany(args.limit + 1)
    headers = [d[0] for d in cur.description] if cur.description else []
    truncated = len(rows) > args.limit
    print(render(rows[: args.limit], headers, args.width))
    if truncated:
        print(f"… more rows; re-run with a narrower query or a higher --limit", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

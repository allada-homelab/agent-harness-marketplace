#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Search the agent-transcripts index and rank sessions by how much they talk about a term.

Unlike `query.py` (which runs one arbitrary SELECT), `search.py` builds the FTS join for
you and adds the two knobs that make a real hunt usable:

- **Boilerplate filtering.** The injected standing instructions (e.g. the AGENTS.md
  "always check for a dev container first" rule) are flagged `injected` by the ingest
  `annotate` pass. `--exclude-injected` drops those messages so hit counts reflect what a
  session actually *did*, not the instruction text that appears in every session.
- **Error-context ranking.** `--errors` sorts by the number of matches that also carry a
  failure signal (`error`, `failed`, `permission denied`, `not found`, `exit code`, …), so
  the sessions that actually hit a problem float to the top instead of the ones that merely
  mentioned the term.

    uv run --script ./search.py --term 'devcontainer' --harness dsh --exclude-injected --errors
    uv run --script ./search.py --term '"devcontainer-cli"' --min-hits 3

Results are capped and truncated exactly like `query.py`.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

DEFAULT_DEST_NAME = "agent-transcripts"

# Substrings (case-insensitive, matched with LIKE) that suggest a message is reporting a
# failure rather than just mentioning the term. Kept wordy but plain so the LIKE is cheap.
ERROR_KEYWORDS = (
    "error",
    "failed",
    "failure",
    "exception",
    "traceback",
    "denied",
    "refused",
    "not found",
    "no such file",
    "exit code",
    "sigterm",
    "timed out",
    "timeout",
    "stack trace",
    "unreachable",
    "cannot",
    "unable",
    "invalid",
    "missing",
    "fatal",
    "crash",
    "abort",
)


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


def quote_term(term: str) -> str:
    """Quote each bare token that contains a hyphen/punctuation so FTS5 does not parse it
    as operators. Already-quoted tokens are left alone."""
    out = []
    for tok in term.split():
        if (tok.startswith('"') and tok.endswith('"')) or re.fullmatch(r"\w+", tok):
            out.append(tok)
        else:
            out.append('"%s"' % tok.replace('"', '""'))
    return " ".join(out)


def render(rows: list, headers: list[str], width: int) -> str:
    """One row per line, every cell truncated to `width` characters."""
    def cell(v):
        s = "" if v is None else str(v)
        s = s.replace("\n", "\\n").replace("\t", " ")
        return s if len(s) <= width else s[:width] + f"…(+{len(s) - width})"

    out = [" | ".join(headers)]
    out += [" | ".join(cell(v) for v in row) for row in rows]
    return "\n".join(out)


def build_query(args) -> tuple[str, list]:
    """Assemble the FTS search SQL and its positional params."""
    conds = ["messages_fts MATCH ?"]
    params: list = [quote_term(args.term)]
    if args.exclude_injected:
        conds.append("m.injected = 0")
    if args.harness:
        h = [h.strip() for h in args.harness.split(",") if h.strip()]
        conds.append(f"s.harness IN ({','.join('?' * len(h))})")
        params.extend(h)
    if args.roles:
        r = [x.strip() for x in args.roles.split(",") if x.strip()]
        conds.append(f"m.role IN ({','.join('?' * len(r))})")
        params.extend(r)

    err_cond = " OR ".join(f"m.text LIKE '%{kw}%'" for kw in ERROR_KEYWORDS)
    select = (
        "SELECT s.id, s.native_id, s.title, s.started_at,"
        " count(*) AS hits,"
        f" sum(CASE WHEN ({err_cond}) THEN 1 ELSE 0 END) AS error_hits"
        " FROM messages_fts"
        " JOIN messages m ON m.id = messages_fts.rowid"
        " JOIN sessions s ON s.id = m.session_id"
        f" WHERE {' AND '.join(conds)}"
        " GROUP BY 1,2,3,4"
    )
    having = []
    if args.min_hits:
        having.append("count(*) >= ?")
        params.append(args.min_hits)
    if having:
        select += " HAVING " + " AND ".join(having)
    order = "error_hits DESC, hits DESC" if args.errors else "hits DESC"
    select += f" ORDER BY {order}"
    return select, params


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--term", required=True, help="FTS match string (hyphenated tokens auto-quoted)")
    ap.add_argument("--dest")
    ap.add_argument("--harness", help="comma list, e.g. 'dsh' or 'claude,dsh' (default: all)")
    ap.add_argument("--roles", help="comma list of roles to include (default: all)")
    ap.add_argument("--exclude-injected", action="store_true",
                    help="drop messages flagged `injected` (standing instructions)")
    ap.add_argument("--errors", action="store_true",
                    help="rank by matches that also carry a failure signal")
    ap.add_argument("--min-hits", type=int, help="only sessions with at least N matches")
    ap.add_argument("--limit", type=int, default=50, help="max rows printed (default 50)")
    ap.add_argument("--width", type=int, default=200, help="max chars per cell (default 200)")
    args = ap.parse_args(argv)

    conn = connect(resolve_dest(args.dest))
    sql, params = build_query(args)
    cur = conn.execute(sql, tuple(params))
    rows = cur.fetchmany(args.limit + 1)
    headers = [d[0] for d in cur.description] if cur.description else []
    truncated = len(rows) > args.limit
    print(render(rows[: args.limit], headers, args.width))
    if truncated:
        print("… more rows; re-run with a narrower query or a higher --limit", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

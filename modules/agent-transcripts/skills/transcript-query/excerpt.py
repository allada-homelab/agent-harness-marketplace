#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Write bounded per-session excerpts for a matched set, into a durable work dir.

This is the "give me a readable, capped look at each of these sessions" step that sits
between `search.py` (which sessions) and a human/subagent judgement (what happened).
It generalizes the one-off script used to audit devcontainer sessions: for every session
it writes one file with a header, the first main-path user message, a **head** sample and a
**tail** sample of the matching messages, plus truncation flags so an auditor knows when an
excerpt is incomplete.

Output lives in a **durable, non-repo** work dir (default
`~/.cache/agent-transcripts/work/<run>/`) with a `manifest.json`, so a run can be handed to
another agent and re-read without re-running the search.

    # 336 sessions that mention devcontainer, one bounded excerpt each, durable.
    uv run --script ./excerpt.py --term 'devcontainer' --harness dsh --run devcontainer-audit

    # Explicit sessions, and read the messages AFTER the head window.
    uv run --script ./excerpt.py --ids 18651,18761 --run devcontainer-audit
    uv run --script ./excerpt.py --next 18651 --offset 30 --count 30
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DEST_NAME = "agent-transcripts"
DEFAULT_WORK_NAME = "work"


def resolve_dest(cli_dest: str | None) -> Path:
    """--dest > $AGENT_TRANSCRIPT_DIR > <user cache dir>/agent-transcripts."""
    if cli_dest:
        return Path(cli_dest).expanduser()
    if os.environ.get("AGENT_TRANSCRIPT_DIR"):
        return Path(os.environ["AGENT_TRANSCRIPT_DIR"]).expanduser()
    cache = os.environ.get("XDG_CACHE_HOME")
    root = Path(cache).expanduser() if cache else Path.home() / ".cache"
    return root / DEFAULT_DEST_NAME


def resolve_work(cli_work: str | None, run: str) -> Path:
    """--work > <index root>/work/<run>; the index root is the transcript cache."""
    if cli_work:
        return Path(cli_work).expanduser()
    return resolve_dest(None).parent / DEFAULT_WORK_NAME / run


def connect(dest_root: Path) -> sqlite3.Connection:
    """Read-only so a query can never lock or corrupt an index an ingest is writing."""
    db = dest_root / "transcripts.db"
    if not db.exists():
        raise SystemExit(f"no index at {db}; run the transcript-ingest skill first")
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def quote_term(term: str) -> str:
    """Quote each bare token containing a hyphen/punctuation so FTS5 does not parse it as
    an operator; already-quoted tokens are left alone."""
    out = []
    for tok in term.split():
        if (tok.startswith('"') and tok.endswith('"')) or re.fullmatch(r"\w+", tok):
            out.append(tok)
        else:
            out.append('"%s"' % tok.replace('"', '""'))
    return " ".join(out)


def cap(s: str | None, n: int) -> str:
    if s is None:
        return ""
    s = str(s).replace("\n", " ⏎ ")
    return s if len(s) <= n else s[:n] + f" …[+{len(s) - n}]"


def session_ids(conn, args) -> list[int]:
    """Resolve the session set from --term (FTS match) or --ids."""
    if args.ids:
        return [int(x) for x in args.ids.split(",") if x.strip()]
    conds = ["messages_fts MATCH ?"]
    params: list = [quote_term(args.term)]
    if args.exclude_injected:
        conds.append("m.injected = 0")
    if args.harness:
        h = [x.strip() for x in args.harness.split(",") if x.strip()]
        conds.append(f"s.harness IN ({','.join('?' * len(h))})")
        params.extend(h)
    if args.roles:
        r = [x.strip() for x in args.roles.split(",") if x.strip()]
        conds.append(f"m.role IN ({','.join('?' * len(r))})")
        params.extend(r)
    sql = (
        "SELECT DISTINCT s.id FROM messages_fts"
        " JOIN messages m ON m.id = messages_fts.rowid"
        " JOIN sessions s ON s.id = m.session_id"
        f" WHERE {' AND '.join(conds)} ORDER BY s.id"
    )
    return [row[0] for row in conn.execute(sql, tuple(params))]


def matching_rows(conn, sid: int, term: str, args):
    """All matching (ord, role, ts, text) for a session, ordered, honoring filters."""
    conds = ["messages_fts MATCH ?", "m.session_id = ?"]
    params: list = [quote_term(term), sid]
    if args.exclude_injected:
        conds.append("m.injected = 0")
    if args.roles:
        r = [x.strip() for x in args.roles.split(",") if x.strip()]
        conds.append(f"m.role IN ({','.join('?' * len(r))})")
        params.extend(r)
    sql = (
        "SELECT m.ord, m.role, m.ts, m.text FROM messages_fts"
        " JOIN messages m ON m.id = messages_fts.rowid"
        f" WHERE {' AND '.join(conds)} ORDER BY m.ord"
    )
    return conn.execute(sql, tuple(params)).fetchall()


def first_user_message(conn, sid: int) -> tuple | None:
    return conn.execute(
        "SELECT ts, text FROM messages WHERE session_id = ? AND role = 'user'"
        " AND on_main_path = 1 ORDER BY ord LIMIT 1",
        (sid,),
    ).fetchone()


def write_excerpt(conn, sid: int, args, meta: dict) -> tuple[Path, int, int, bool]:
    """Write one excerpt file; return (path, total_matches, written, truncated)."""
    rows = matching_rows(conn, sid, args.term, args)
    total = len(rows)
    head = rows[: args.head]
    tail = rows[-args.tail :] if total > args.head + args.tail else []
    truncated = total > args.head + args.tail
    written = len(head) + len(tail)

    lines = [
        f"# session_id={sid}",
        f"# native_id={meta.get('native_id','?')}",
        f"# title={cap(meta.get('title'), 160)}",
        f"# project_key={cap(meta.get('project_key'), 120)}",
        f"# started_at={meta.get('started_at','?')}",
        f"# term={args.term}",
        f"# matching_messages={total}  truncated={'yes' if truncated else 'no'}",
        "# " + "-" * 70,
    ]
    if args.include_user:
        um = first_user_message(conn, sid)
        if um:
            lines.append("## FIRST USER MESSAGE")
            lines.append(f"({cap(um[0], 30)})")
            lines.append(cap(um[1], args.user_width))
            lines.append("")
    lines.append(f"## MATCHING MESSAGES (head {len(head)} + tail {len(tail)})")
    for ord_, role, ts, text in head:
        lines.append(f"[{role} {cap(ts, 30)}]")
        lines.append(cap(text, args.width))
    if truncated:
        lines.append(f"… [{total - len(head) - len(tail)} messages omitted between head and tail]")
    for ord_, role, ts, text in tail:
        lines.append(f"[{role} {cap(ts, 30)}]")
        lines.append(cap(text, args.width))

    excerpt_dir = args.work / "excerpts"
    excerpt_dir.mkdir(parents=True, exist_ok=True)
    path = excerpt_dir / f"{sid}.txt"
    path.write_text("\n".join(lines) + "\n")
    return path, total, written, truncated


def cmd_next(conn, args) -> int:
    """Print the next chunk of matching messages for a session after an offset."""
    rows = matching_rows(conn, args.next, args.term, args)
    window = rows[args.offset : args.offset + args.count]
    if not window:
        print(f"no matching messages for session {args.next} at offset {args.offset}")
        return 0
    print(f"# session {args.next} matching messages {args.offset}–{args.offset + len(window)} of {len(rows)}")
    for ord_, role, ts, text in window:
        print(f"[{role} {cap(ts, 30)}]")
        print(cap(text, args.width))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--term", help="FTS match string (hyphenated tokens auto-quoted)")
    ap.add_argument("--ids", help="comma list of session ids (mutually exclusive with --term)")
    ap.add_argument("--dest")
    ap.add_argument("--work", help="work dir (default <index root>/work/<run>)")
    ap.add_argument("--run", default=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
                    help="run name for the work dir (default: timestamp)")
    ap.add_argument("--harness", help="comma list, e.g. 'dsh' (default: all)")
    ap.add_argument("--roles", help="comma list of roles to include (default: all)")
    ap.add_argument("--exclude-injected", action="store_true",
                    help="drop messages flagged `injected` (standing instructions)")
    ap.add_argument("--include-user", action="store_true", default=True,
                    help="include the first main-path user message (default)")
    ap.add_argument("--no-user", action="store_true", help="omit the first user message")
    ap.add_argument("--head", type=int, default=30, help="matching messages to take from the start (default 30)")
    ap.add_argument("--tail", type=int, default=10, help="matching messages to take from the end (default 10)")
    ap.add_argument("--width", type=int, default=700, help="chars per matching message (default 700)")
    ap.add_argument("--user-width", type=int, default=1200, help="chars for the first user message (default 1200)")
    # --next chunk-read mode
    ap.add_argument("--next", type=int, help="session id: print the next chunk of matching messages")
    ap.add_argument("--offset", type=int, default=30, help="offset for --next (default: head)")
    ap.add_argument("--count", type=int, default=30, help="how many messages for --next (default 30)")
    ap.add_argument("--json", action="store_true", help="also print the manifest JSON to stdout")
    args = ap.parse_args(argv)

    if not args.term and not args.ids:
        ap.error("one of --term or --ids is required")
    if args.term and args.ids:
        ap.error("--term and --ids are mutually exclusive")
    args.include_user = not args.no_user
    args.work = resolve_work(args.work, args.run)

    conn = connect(resolve_dest(args.dest))

    if args.next is not None:
        if not args.term:
            ap.error("--next requires --term so the matching set is known")
        return cmd_next(conn, args)

    ids = session_ids(conn, args)
    manifest = {
        "run": args.run,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "term": args.term,
        "ids_provided": bool(args.ids),
        "harness": args.harness,
        "roles": args.roles,
        "exclude_injected": args.exclude_injected,
        "head": args.head,
        "tail": args.tail,
        "width": args.width,
        "user_width": args.user_width,
        "session_count": len(ids),
        "sessions": [],
    }
    for sid in ids:
        meta_row = conn.execute(
            "SELECT native_id, title, project_key, started_at FROM sessions WHERE id = ?",
            (sid,),
        ).fetchone()
        meta = {
            "native_id": meta_row[0] if meta_row else None,
            "title": meta_row[1] if meta_row else None,
            "project_key": meta_row[2] if meta_row else None,
            "started_at": meta_row[3] if meta_row else None,
        }
        path, total, written, truncated = write_excerpt(conn, sid, args, meta)
        manifest["sessions"].append({
            "id": sid,
            "file": str(path),
            "size": path.stat().st_size,
            "total_matches": total,
            "written": written,
            "truncated": truncated,
        })

    manifest_path = args.work / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    conn.close()
    n_trunc = sum(1 for s in manifest["sessions"] if s["truncated"])
    print(f"excerpt: run={args.run} sessions={len(ids)} files={len(ids)} truncated={n_trunc} work={args.work}")
    if args.json:
        print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

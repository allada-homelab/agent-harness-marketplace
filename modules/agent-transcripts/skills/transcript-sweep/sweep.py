#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Sweep the agent-transcripts index for obvious and potential problems, one JSONL per flag.

Deterministic first pass: no model reads a transcript here. The sweep streams tool calls in
session order, keeps a little per-session state, and writes one record per session per flag
kind. A later analysis skill reads the JSONL; this script only counts and quotes at most a
200-character snippet of a tool result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DEST_NAME = "agent-transcripts"
SNIPPET = 200
MAX_EVIDENCE = 3
RETRY_WINDOW = 2  # a repeat within this many following tool calls counts as a retry
STREAK_MIN = 3

ISSUE, POTENTIAL = "issue", "potential"
KINDS = (
    ("tool_error", ISSUE),
    ("error_streak", ISSUE),
    ("retry_same_input_after_error", ISSUE),
    ("duplicate_call", POTENTIAL),
    ("bash_substitute", POTENTIAL),
    ("long_result", POTENTIAL),
    ("long_session", POTENTIAL),
)

# First match wins, case-insensitive, against the result snippet.
SIGNATURES = (
    ("permission_denied", re.compile(r"permission denied|not allowed|denied", re.I)),
    ("edit_anchor_miss", re.compile(r"old_string|hash mismatch|no match|not unique", re.I)),
    ("file_not_found", re.compile(r"no such file|not found|ENOENT", re.I)),
    ("nonzero_exit", re.compile(r"exit code [1-9]|exited with code [1-9]", re.I)),
)

# claude spells it Bash, pi and dsh spell it bash; dsh's run_code is a code runner, not a shell.
SHELL_TOOLS = {"bash"}
SHELL_ARG_KEYS = ("command", "cmd", "script")

# A read-only one-liner a dedicated tool does better. Whole command only: chained diagnostics
# are legitimate, and a "contains cat/grep" rule fires on about half of all shell calls.
READ_ONLY_VERBS = ("cat", "head", "tail", "grep", "rg", "find", "ls", "sed")
CD_PREFIX = re.compile(r"^cd\s+[^\s;&|<>()$`'\"]+\s*&&\s*")
TRAILING_PIPE = re.compile(r"\s*\|\s*(?:head|tail)(?:\s+-\w+)?(?:\s+\d+)?\s*$|\s*\|\s*wc\s+-l\s*$")
FORBIDDEN_IN_CORE = set("|&;<>()`\n")


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
    """Read-only so a sweep can never lock or corrupt an index an ingest is writing."""
    db = dest_root / "transcripts.db"
    if not db.exists():
        raise SystemExit(f"no index at {db}; run the transcript-ingest skill first")
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def current_parser_version() -> int:
    """Read PARSER_VERSION out of the ingest script rather than keeping a copy of the number.

    Read, not imported: that script declares a third-party dependency this one does not need.
    """
    src = Path(__file__).resolve().parent.parent / "transcript-ingest" / "transcripts.py"
    if not src.exists():
        raise SystemExit(f"cannot read the parser version: {src} is missing")
    match = re.search(r"^PARSER_VERSION\s*=\s*(\d+)", src.read_text(encoding="utf-8"), re.M)
    if not match:
        raise SystemExit(f"cannot find PARSER_VERSION in {src}")
    return int(match.group(1))


def db_parser_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT min(parser_version) FROM files").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


# ------------------------------------------------------------------ classifying


def normalize_arguments(raw: str | None) -> str:
    """Key order must not make two identical calls look different."""
    if raw is None:
        return ""
    try:
        return json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":"))
    except (ValueError, TypeError):
        return raw.strip()


def signature(snippet: str | None) -> str:
    for name, pattern in SIGNATURES:
        if snippet and pattern.search(snippet):
            return name
    return "other"


def shell_command(name: str | None, raw: str | None) -> str | None:
    """The command string of a shell tool call, or None if this is not one."""
    if not name or name.lower() not in SHELL_TOOLS:
        return None
    try:
        args = json.loads(raw) if raw else None
    except (ValueError, TypeError):
        return None
    if not isinstance(args, dict):
        return None
    for key in SHELL_ARG_KEYS:
        value = args.get(key)
        if isinstance(value, str):
            return value
    return None


def is_bash_substitute(command: str) -> bool:
    """True when the whole command is a single invocation of a listing/reading command."""
    core = TRAILING_PIPE.sub("", CD_PREFIX.sub("", command.strip()), count=1).strip()
    if not core or FORBIDDEN_IN_CORE & set(core):
        return False
    tokens = core.split()
    verb = tokens[0]
    if verb not in READ_ONLY_VERBS:
        return False
    if verb == "sed":  # only the print-range form; a sed script edits
        return len(tokens) > 1 and tokens[1] == "-n"
    return True


# ---------------------------------------------------------------------- sweeping


def _fingerprint(name: str | None, norm: str) -> str:
    """Hash the arguments: a session can hold megabyte-sized ones and state stays per-session."""
    return hashlib.sha1(f"{name}\0{norm}".encode(), usedforsecurity=False).hexdigest()


class SessionState:
    """Every counter one session needs, updated per tool call in one pass."""

    def __init__(self, row):
        self.session_id, self.native_id, self.harness, self.cwd, self.started_at = row[:5]
        self.calls = 0
        self.errors = 0
        self.error_evidence: list[dict] = []
        self.signatures: Counter = Counter()
        self.streak = 0
        self.streaks = 0
        self.max_streak = 0
        self.streak_evidence: list[dict] = []
        self.recent: deque = deque(maxlen=RETRY_WINDOW)
        self.retries = 0
        self.retry_names: Counter = Counter()
        self.retry_evidence: list[dict] = []
        self.seen: Counter = Counter()
        self.duplicates = 0
        self.max_repeat = 0
        self.duplicate_evidence: list[dict] = []
        self.bash_subs = 0
        self.bash_verbs: Counter = Counter()
        self.bash_evidence: list[dict] = []
        self.long_results = 0
        self.max_result = 0
        self.long_evidence: list[dict] = []

    def add(self, row, long_result: int) -> None:
        (_, _, _, _, _, call_id, message_id, name, arguments, is_error,
         result_len, result_snippet) = row
        self.calls += 1
        norm = normalize_arguments(arguments)
        key = _fingerprint(name, norm)

        def evidence(bucket: list[dict], snippet: str | None) -> None:
            if len(bucket) < MAX_EVIDENCE:
                bucket.append({
                    "tool_call_id": call_id,
                    "message_id": message_id,
                    "name": name,
                    "snippet": (snippet or "")[:SNIPPET],
                })

        if is_error:
            self.errors += 1
            self.signatures[signature(result_snippet)] += 1
            evidence(self.error_evidence, result_snippet)
            self.streak += 1
            self.max_streak = max(self.max_streak, self.streak)
            if self.streak == STREAK_MIN:
                self.streaks += 1
                evidence(self.streak_evidence, result_snippet)
        else:
            self.streak = 0

        for prev_key, prev_error in self.recent:
            if prev_error and prev_key == key:
                self.retries += 1
                self.retry_names[name] += 1
                evidence(self.retry_evidence, norm)
                break
        self.recent.append((key, bool(is_error)))

        self.seen[key] += 1
        if self.seen[key] >= 2:
            self.duplicates += 1
            self.max_repeat = max(self.max_repeat, self.seen[key])
            if self.seen[key] == 2:
                evidence(self.duplicate_evidence, norm)

        command = shell_command(name, arguments)
        if command and is_bash_substitute(command):
            self.bash_subs += 1
            self.bash_verbs[CD_PREFIX.sub("", command.strip()).split()[0]] += 1
            evidence(self.bash_evidence, command)

        if result_len and result_len > long_result:
            self.long_results += 1
            self.max_result = max(self.max_result, result_len)
            evidence(self.long_evidence, result_snippet)

    def records(self, long_result: int, long_session: int) -> list[dict]:
        found = {
            "tool_error": (self.errors, {"signatures": dict(self.signatures)}, self.error_evidence),
            "error_streak": (
                self.streaks,
                {"streaks": self.streaks, "max_len": self.max_streak},
                self.streak_evidence,
            ),
            "retry_same_input_after_error": (
                self.retries,
                {"names": dict(self.retry_names)},
                self.retry_evidence,
            ),
            "duplicate_call": (
                self.duplicates,
                {"groups": sum(1 for n in self.seen.values() if n >= 2),
                 "max_repeat": self.max_repeat},
                self.duplicate_evidence,
            ),
            "bash_substitute": (
                self.bash_subs,
                {"commands": dict(self.bash_verbs)},
                self.bash_evidence,
            ),
            "long_result": (
                self.long_results,
                {"threshold": long_result, "max_length": self.max_result},
                self.long_evidence,
            ),
            "long_session": (
                1 if self.calls > long_session else 0,
                {"threshold": long_session, "tool_calls": self.calls},
                [],
            ),
        }
        out = []
        for kind, severity in KINDS:
            count, detail, evidence = found[kind]
            if not count:
                continue
            out.append({
                "session_id": self.session_id,
                "native_id": self.native_id,
                "harness": self.harness,
                "cwd": self.cwd,
                "started_at": self.started_at,
                "kind": kind,
                "severity": severity,
                "count": count,
                "detail": detail,
                "evidence": evidence,
            })
        return out


STREAM_SQL = """
SELECT s.id, s.native_id, s.harness, s.cwd, s.started_at,
       t.id, t.message_id, t.name, t.arguments, t.is_error,
       length(r.text), substr(r.text, 1, {snippet})
FROM tool_calls t
JOIN messages m ON m.id = t.message_id
JOIN sessions s ON s.id = m.session_id
LEFT JOIN messages r ON r.id = t.result_message_id
{where}
ORDER BY s.id, m.ord, t.id
"""


def _filters(since, harnesses, session) -> tuple[str, list]:
    clauses, params = [], []
    if since:
        clauses.append("s.started_at >= ?")
        params.append(since)
    if harnesses:
        clauses.append("s.harness IN (%s)" % ",".join("?" for _ in harnesses))
        params += list(harnesses)
    if session:
        clauses.append("(s.native_id = ? OR s.id = ?)")
        params += [session, int(session) if session.isdigit() else -1]
    return ("WHERE " + " AND ".join(clauses) if clauses else ""), params


def sweep(conn, since=None, harnesses=None, session=None, long_result=5000, long_session=150):
    """Yield one record per session per flag kind, streaming; never holds a table in memory."""
    where, params = _filters(since, harnesses, session)
    cur = conn.execute(STREAM_SQL.format(snippet=SNIPPET, where=where), params)
    state = None
    for row in cur:
        if state is None or row[0] != state.session_id:
            if state is not None:
                yield from state.records(long_result, long_session)
            state = SessionState(row)
        state.add(row, long_result)
    if state is not None:
        yield from state.records(long_result, long_session)


def count_sessions(conn, since, harnesses, session) -> int:
    where, params = _filters(since, harnesses, session)
    return conn.execute(f"SELECT count(*) FROM sessions s {where}", params).fetchone()[0]


# --------------------------------------------------------------------- reporting


class Summary:
    """Counters only: the records themselves go to the JSONL, never into a list in memory."""

    def __init__(self):
        self.records = 0
        self.grid: Counter = Counter()
        self.per_session: dict = {}

    def add(self, rec: dict) -> None:
        self.records += 1
        self.grid[(rec["harness"], rec["kind"])] += rec["count"]
        entry = self.per_session.setdefault(
            rec["session_id"],
            {"native_id": rec["native_id"], "harness": rec["harness"],
             "started_at": rec["started_at"], ISSUE: 0, POTENTIAL: 0},
        )
        entry[rec["severity"]] += rec["count"]

    def render(self, scanned: int, out_path: Path, top: int) -> str:
        kinds = [k for k, _ in KINDS]
        harnesses = sorted({h for h, _ in self.grid})
        width = max([len(h) for h in harnesses] + [len("harness")])
        lines = [f"wrote {self.records} records to {out_path}", ""]
        lines.append(" ".join(["harness".ljust(width)] + kinds))
        for harness in harnesses:
            cells = [str(self.grid[(harness, k)]).rjust(len(k)) for k in kinds]
            lines.append(" ".join([harness.ljust(width)] + cells))
        lines += ["", f"sessions scanned: {scanned}    sessions flagged: {len(self.per_session)}"]

        ranked = sorted(
            self.per_session.values(), key=lambda s: (-s[ISSUE], -s[POTENTIAL])
        )[:top]
        if ranked:
            lines += ["", f"top {len(ranked)} sessions by issue count:",
                      "native_id | harness | started_at | issues | potential"]
            for s in ranked:
                lines.append(
                    f"{s['native_id']} | {s['harness']} | {s['started_at']} | "
                    f"{s[ISSUE]} | {s[POTENTIAL]}"
                )
        return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dest", help="cache root (same resolution as the query and ingest skills)")
    ap.add_argument("--since", help="only sessions whose started_at is >= this ISO8601 timestamp")
    ap.add_argument("--harness", action="append", choices=["claude", "pi", "dsh"],
                    help="limit to one harness; repeatable")
    ap.add_argument("--session", help="one session, by native_id or numeric id")
    ap.add_argument("--out", help="JSONL path (default <dest>/sweeps/<UTC timestamp>.jsonl)")
    ap.add_argument("--long-result", type=int, default=5000,
                    help="a tool result longer than this is flagged (default 5000)")
    ap.add_argument("--long-session", type=int, default=150,
                    help="a session with more tool calls than this is flagged (default 150)")
    ap.add_argument("--top", type=int, default=20, help="sessions listed in the summary (default 20)")
    args = ap.parse_args(argv)

    dest = resolve_dest(args.dest)
    conn = connect(dest)
    have, want = db_parser_version(conn), current_parser_version()
    if have < want:
        print(
            f"index was built by parser version {have}, this sweep needs {want}; "
            "run the transcript-ingest skill (ingest --rebuild) first",
            file=sys.stderr,
        )
        return 2

    if args.out:
        out_path = Path(args.out).expanduser()
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = dest / "sweeps" / f"{stamp}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    summary = Summary()
    with out_path.open("w", encoding="utf-8") as fh:
        for rec in sweep(conn, args.since, args.harness, args.session,
                         args.long_result, args.long_session):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            summary.add(rec)

    scanned = count_sessions(conn, args.since, args.harness, args.session)
    print(summary.render(scanned, out_path, args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

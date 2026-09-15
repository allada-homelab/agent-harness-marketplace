#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""The findings store: what the sweep and the review skills learned about a session.

`findings.db` sits beside `transcripts.db` in the cache root but is a separate database on
purpose: the index is rebuildable and its `sessions.id` values change on every rebuild, so a
finding is keyed by `(harness, native_id)` — the identity the raw transcript carries — and
survives an ingest --rebuild.

Imported, not run: the sweep and review scripts put this directory on `sys.path` and
`import findings`.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

FINDINGS_NAME = "findings.db"
# Bumped whenever a CREATE TABLE here changes: the statements are IF NOT EXISTS, so an
# existing file would otherwise keep the old shape forever. Stored in PRAGMA user_version.
SCHEMA_VERSION = 1

FINDINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    skill       TEXT NOT NULL,
    model       TEXT,
    started_at  TEXT NOT NULL,
    args        TEXT
);

CREATE TABLE IF NOT EXISTS sweep_flags (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    harness     TEXT NOT NULL,
    native_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,
    severity    TEXT NOT NULL,
    count       INTEGER NOT NULL,
    detail      TEXT NOT NULL,
    evidence    TEXT NOT NULL,
    UNIQUE(harness, native_id, kind)
);

CREATE TABLE IF NOT EXISTS review_flags (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES runs(id),
    harness      TEXT NOT NULL,
    native_id    TEXT NOT NULL,
    category     TEXT NOT NULL,
    present      INTEGER NOT NULL CHECK(present IN (0,1)),
    confidence   TEXT NOT NULL CHECK(confidence IN ('low','medium','high')),
    evidence_ord INTEGER,
    quote        TEXT,
    note         TEXT,
    created_at   TEXT NOT NULL,
    UNIQUE(run_id, harness, native_id, category)
);

CREATE INDEX IF NOT EXISTS sweep_flags_session ON sweep_flags(harness, native_id);
CREATE INDEX IF NOT EXISTS review_flags_session ON review_flags(harness, native_id);
CREATE INDEX IF NOT EXISTS review_flags_category ON review_flags(category, present);
CREATE INDEX IF NOT EXISTS review_flags_run ON review_flags(run_id);
"""


def open_findings(dest: Path, *, readonly: bool = False) -> sqlite3.Connection:
    """Open `<dest>/findings.db`, creating and migrating it unless `readonly`.

    Read-only callers get a `file:…?mode=ro` connection and a SystemExit naming the sweep
    when the store does not exist yet — the same shape the index connections use.
    """
    db = Path(dest) / FINDINGS_NAME
    if readonly:
        if not db.exists():
            raise SystemExit(f"no findings store at {db}; run the transcript-sweep skill first")
        return sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    migrate(conn, db)
    conn.executescript(FINDINGS_SCHEMA)
    conn.commit()
    return conn


def migrate(conn: sqlite3.Connection, db: Path) -> None:
    """Bring an older file up to SCHEMA_VERSION, or refuse to touch it.

    The only migration so far drops `review_flags` so the schema below can recreate it with
    its UNIQUE key. That is destructive, so it only runs while the table is empty; a store
    that already holds review findings is the user's data and this exits rather than guess.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'review_flags'"
    ).fetchone()
    if existing:
        rows = conn.execute("SELECT count(*) FROM review_flags").fetchone()[0]
        if rows:
            print(
                f"{db} was written by schema version {version}, this code needs "
                f"{SCHEMA_VERSION}, and the upgrade recreates review_flags — but it holds "
                f"{rows} rows. Move the file aside (rename it) and re-run the sweep and the "
                "review to rebuild it; nothing was changed.",
                file=sys.stderr,
            )
            conn.close()
            raise SystemExit(2)
        conn.execute("DROP TABLE review_flags")
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def start_run(conn: sqlite3.Connection, skill: str, model: str | None, args) -> int:
    """Record one invocation and return its id; `args` is JSON-encoded unless already a string."""
    if args is not None and not isinstance(args, str):
        args = json.dumps(args, ensure_ascii=False)
    cur = conn.execute(
        "INSERT INTO runs (skill, model, started_at, args) VALUES (?, ?, ?, ?)",
        (skill, model, datetime.now(timezone.utc).isoformat(timespec="seconds"), args),
    )
    conn.commit()
    return int(cur.lastrowid)


def replace_sweep_flags(conn, run_id: int, harness: str, native_id: str, records) -> int:
    """Make `records` the session's whole set of sweep flags; returns how many were inserted.

    Delete and insert share one implicit transaction, so a session is never half-flagged. The
    caller commits — a sweep writes thousands of sessions and a commit each would dominate it.
    """
    conn.execute(
        "DELETE FROM sweep_flags WHERE harness = ? AND native_id = ?", (harness, native_id)
    )
    rows = [
        (
            run_id,
            harness,
            native_id,
            rec["kind"],
            rec["severity"],
            rec["count"],
            json.dumps(rec.get("detail") or {}, ensure_ascii=False),
            json.dumps(rec.get("evidence") or [], ensure_ascii=False),
        )
        for rec in records
    ]
    conn.executemany(
        "INSERT INTO sweep_flags (run_id, harness, native_id, kind, severity, count,"
        " detail, evidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)

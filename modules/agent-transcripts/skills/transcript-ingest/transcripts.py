#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["zstandard"]
# ///
"""Export Claude Code, pi and dsh transcripts on-device, then index them.

Export is read-only and incremental: raw session files from host directories and
from docker named volumes used by dev containers are copied under
`<root>/raw/<harness>/<source>/<subdir>/…` with a merged `manifest.json`.

Sources are never mutated: volume reads run in a throwaway `alpine` container with
the volume mounted `:ro`. The output root must never be inside a git worktree.

    uv run --script transcripts.py export claude|pi|dsh [--dry-run] [--dest DIR] [--json]
    uv run --script transcripts.py ingest [--dest DIR] [--rebuild]   # 75 = another run holds the lock
    uv run --script transcripts.py annotate [--dest DIR] [--min-sessions N] [--exclude-role R]
    uv run --script transcripts.py fts    [--dest DIR]   # rebuild the full-text index
    uv run --script transcripts.py stats  [--dest DIR]
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HARNESSES = ("claude", "pi", "dsh")
DEFAULT_DEST_NAME = "agent-transcripts"

# Tier-3 name-pattern sweeps for orphaned volumes whose containers were deleted.
CLAUDE_VOLUME_PATTERNS = ("claude-code-config-*", "*-claude-*")
DSH_VOLUME_PATTERNS = ("*deepseek*",)

# ingest diagnostics on stderr: a progress line this often, and a line for any
# single file slower than this, so a long rebuild shows where its time goes.
PROGRESS_EVERY_S = 30.0
SLOW_FILE_S = 2.0


# ---------------------------------------------------------------- destination


def resolve_dest(cli_dest: str | None) -> Path:
    """CLI --dest > $AGENT_TRANSCRIPT_DIR > <cache dir>/agent-transcripts, then guard."""
    if cli_dest:
        dest = Path(cli_dest).expanduser()
    elif os.environ.get("AGENT_TRANSCRIPT_DIR"):
        dest = Path(os.environ["AGENT_TRANSCRIPT_DIR"]).expanduser()
    else:
        cache = os.environ.get("XDG_CACHE_HOME")
        base = Path(cache).expanduser() if cache else Path.home() / ".cache"
        dest = base / DEFAULT_DEST_NAME
    dest = dest.resolve()
    assert_outside_worktree(dest)
    return dest


def assert_outside_worktree(path: Path) -> None:
    """Abort if `path`'s nearest existing ancestor is inside a git worktree."""
    anchor = path
    while not anchor.exists() and anchor != anchor.parent:
        anchor = anchor.parent
    try:
        res = subprocess.run(
            ["git", "-C", str(anchor), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return  # no git → cannot be a worktree
    if res.returncode == 0 and res.stdout.strip() == "true":
        raise SystemExit(
            f"refusing to export into a git worktree: {anchor} "
            "(transcripts must never enter a repo; set $AGENT_TRANSCRIPT_DIR elsewhere)"
        )


# ------------------------------------------------------------------ discovery


def _docker_volumes(docker: str, dest_suffix: str, patterns: tuple[str, ...]) -> dict:
    """Volumes mounted at `dest_suffix` in any container, plus a name-pattern sweep."""
    volumes: dict[str, dict] = {}
    if shutil.which(docker) is None:
        print(
            f"warning: {docker} not found; exporting host source only", file=sys.stderr
        )
        return volumes

    # Tier 2: containers (running or stopped) with a mount destination ending in dest_suffix.
    try:
        ps = subprocess.run([docker, "ps", "-a", "-q"], capture_output=True, text=True)
        ids = ps.stdout.split() if ps.returncode == 0 else []
        if ids:
            insp = subprocess.run(
                [docker, "inspect", *ids], capture_output=True, text=True
            )
            if insp.returncode == 0:
                for cont in json.loads(insp.stdout or "[]"):
                    cname = cont.get("Name", "").lstrip("/")
                    for m in cont.get("Mounts") or []:
                        if m.get("Type") == "volume" and str(
                            m.get("Destination", "")
                        ).rstrip("/").endswith(dest_suffix):
                            name = m.get("Name")
                            if name and name not in volumes:
                                volumes[name] = {
                                    "kind": "volume",
                                    "name": name,
                                    "origin": f"container:{cname}",
                                }
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(
            f"warning: docker container inspect failed ({e}); continuing",
            file=sys.stderr,
        )

    # Tier 3: name-pattern sweep for orphaned volumes.
    try:
        vls = subprocess.run(
            [docker, "volume", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
        )
        if vls.returncode == 0:
            for name in vls.stdout.split():
                if name in volumes:
                    continue
                if any(fnmatch.fnmatch(name, p) for p in patterns):
                    volumes[name] = {
                        "kind": "volume",
                        "name": name,
                        "origin": "volume-sweep",
                    }
    except FileNotFoundError as e:
        print(f"warning: docker volume ls failed ({e}); continuing", file=sys.stderr)

    return volumes


def discover_claude(docker: str = "docker") -> list[dict]:
    """Host projects dir plus dev-container volumes. Docker absent → host only."""
    sources: list[dict] = []
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    root = Path(base).expanduser() if base else Path.home() / ".claude"
    projects = root / "projects"
    if projects.is_dir():
        sources.append(
            {
                "harness": "claude",
                "kind": "host",
                "name": "host",
                "origin": str(projects),
                "subdir": "projects",
                "skipped": [],
            }
        )
    for vol in _docker_volumes(docker, "/.claude", CLAUDE_VOLUME_PATTERNS).values():
        sources.append(
            {
                "harness": "claude",
                **vol,
                "subdir": "projects",
                "skipped": [],
            }
        )
    return sources


def discover_pi() -> list[dict]:
    """The configured settings session root (when set) and always the default root."""
    base = os.environ.get("PI_CODING_AGENT_DIR")
    agent_dir = Path(base).expanduser() if base else Path.home() / ".pi" / "agent"

    settings_root: Path | None = None
    env_root = os.environ.get("PI_CODING_AGENT_SESSION_DIR")
    if env_root:
        settings_root = Path(env_root).expanduser()
    else:
        settings_file = agent_dir / "settings.json"
        if settings_file.is_file():
            try:
                session_dir = json.loads(settings_file.read_text()).get("sessionDir")
            except (json.JSONDecodeError, OSError) as e:
                print(f"warning: could not read {settings_file} ({e})", file=sys.stderr)
                session_dir = None
            if session_dir:
                settings_root = Path(session_dir).expanduser()

    skipped = ["docker volumes (not scanned in v0.1)", "spill/"]
    sources: list[dict] = []
    if settings_root is not None:
        sources.append(
            {
                "harness": "pi",
                "kind": "host",
                "name": "host",
                "origin": str(settings_root),
                "subdir": "settings",
                "skipped": list(skipped),
            }
        )
    default_root = agent_dir / "sessions"
    if settings_root is None or default_root.resolve() != settings_root.resolve():
        sources.append(
            {
                "harness": "pi",
                "kind": "host",
                "name": "host",
                "origin": str(default_root),
                "subdir": "default",
                "skipped": list(skipped),
            }
        )
    return sources


def discover_dsh(docker: str = "docker") -> list[dict]:
    """Host sessions dir plus dev-container volumes. Files stay zstd-compressed."""
    base = os.environ.get("DSH_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".dsh"
    sessions = root / "sessions"
    skipped = [
        "attachments/",
        "spill/",
        "session.lock",
        "query.sqlite",
        "*.decompressed.jsonl",
    ]
    sources: list[dict] = []
    if sessions.is_dir():
        sources.append(
            {
                "harness": "dsh",
                "kind": "host",
                "name": "host",
                "origin": str(sessions),
                "subdir": "sessions",
                "skipped": list(skipped),
            }
        )
    for vol in _docker_volumes(docker, "/.dsh", DSH_VOLUME_PATTERNS).values():
        sources.append(
            {
                "harness": "dsh",
                **vol,
                "subdir": "sessions",
                "skipped": list(skipped),
            }
        )
    return sources


# --------------------------------------------------------------------- export


def _is_safe_member(name: str) -> bool:
    """Reject tar members that would escape the export root (path-traversal CVE class)."""
    parts = Path(name).parts
    return not (Path(name).is_absolute() or ".." in parts)


def should_copy(size: int, mtime: int, dest_path: Path) -> bool:
    """True unless dest exists with identical size and (integer) mtime."""
    if not dest_path.exists():
        return True
    st = dest_path.stat()
    return size != st.st_size or mtime != int(st.st_mtime)


def _tmp_path(dest: Path) -> Path:
    """Same-directory temp name, so os.replace is an atomic rename and ingest never
    reads a half-copied file; the suffix keeps it out of iter_raw_files' globs."""
    return dest.with_name(f"{dest.name}.{os.getpid()}.tmp")


def _write_member(dest: Path, data: bytes, mtime: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(dest)
    tmp.write_bytes(data)
    os.utime(tmp, (mtime, mtime))  # preserve source mtime so incremental skip works
    os.replace(tmp, dest)


def _source_root(dest_root: Path, src: dict) -> Path:
    return dest_root / "raw" / src["harness"] / src["name"] / src["subdir"]


def _skipped_member(harness: str, rel: Path) -> bool:
    """Side files that sit beside the logs but are not session data.

    pi's third-party `spill/` payloads and dsh's `session.lock` / `query.sqlite`
    / `*.decompressed.jsonl` files are not transcripts; copying them only
    bloats the cache and the manifest counts. The ingest ignores them anyway.
    """
    if harness == "pi":
        return bool(rel.parts) and rel.parts[0] == "spill"
    if harness == "dsh":
        return rel.name in ("session.lock", "query.sqlite") or rel.name.endswith(
            ".decompressed.jsonl"
        )
    return False


def _export_host(src: dict, dest_root: Path, dry_run: bool) -> dict:
    origin = Path(src["origin"])
    base = _source_root(dest_root, src)
    copied = skipped = 0
    if not origin.is_dir():
        return {"copied": copied, "skipped": skipped}
    for f in sorted(origin.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(origin)
        if _skipped_member(src["harness"], rel):
            continue
        dest = base / rel
        st = f.stat()
        if should_copy(st.st_size, int(st.st_mtime), dest):
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = _tmp_path(dest)
                shutil.copy2(f, tmp)  # copy2 preserves mtime
                os.replace(tmp, dest)
            copied += 1
        else:
            skipped += 1
    return {"copied": copied, "skipped": skipped}


def _export_volume(src: dict, dest_root: Path, dry_run: bool, docker: str) -> dict:
    name = src["name"]
    base = dest_root / "raw" / src["harness"] / name
    copied = skipped = 0
    proc = subprocess.Popen(
        [
            docker,
            "run",
            "--rm",
            "-v",
            f"{name}:/v:ro",
            "alpine",
            "tar",
            "-C",
            "/v",
            "-cf",
            "-",
            src["subdir"],
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                if not _is_safe_member(member.name):
                    skipped += 1
                    continue
                if _skipped_member(src["harness"], Path(member.name)):
                    continue
                dest = base / member.name
                if should_copy(member.size, int(member.mtime), dest):
                    if dry_run:
                        copied += 1
                        continue
                    fobj = tar.extractfile(member)
                    if fobj is None:
                        continue
                    _write_member(dest, fobj.read(), int(member.mtime))
                    copied += 1
                else:
                    skipped += 1
    except tarfile.TarError as e:
        print(
            f"warning: could not read tar from volume {name} ({e}); skipping",
            file=sys.stderr,
        )
    finally:
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        rc = proc.wait()
    if rc != 0 and copied == 0 and skipped == 0:
        print(
            f"warning: volume {name} export failed (rc={rc}): {err.strip()}",
            file=sys.stderr,
        )
    return {"copied": copied, "skipped": skipped}


def _source_stats(dest_root: Path, src: dict) -> dict:
    """Aggregate the exported tree for one source: file count, bytes, newest mtime."""
    base = _source_root(dest_root, src)
    files = 0
    total = 0
    newest = 0
    for f in base.rglob("*"):
        if f.is_file():
            st = f.stat()
            files += 1
            total += st.st_size
            newest = max(newest, int(st.st_mtime))
    return {"files": files, "bytes": total, "newest_mtime": newest}


def _load_manifest(dest_root: Path) -> dict:
    path = dest_root / "manifest.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict) and isinstance(data.get("harnesses"), dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"exported_at": None, "harnesses": {}}


def export_sources(
    dest_root: Path, sources: list[dict], dry_run: bool, docker: str = "docker"
) -> dict:
    """Copy every source, then merge its row into the manifest (other harnesses untouched)."""
    manifest = _load_manifest(dest_root)
    harnesses = manifest.setdefault("harnesses", {})
    for src in sources:
        if src["kind"] == "host":
            counts = _export_host(src, dest_root, dry_run)
        else:
            counts = _export_volume(src, dest_root, dry_run, docker)
        suffix = " (dry run)" if dry_run else ""
        print(
            f"{src['harness']}/{src['name']}/{src['subdir']} <- {src['origin']} "
            f"copied={counts['copied']} unchanged={counts['skipped']}{suffix}"
        )
        if dry_run:
            continue
        bucket = harnesses.setdefault(src["harness"], {"sources": []})
        rows = [
            r
            for r in bucket.get("sources", [])
            if (r.get("name"), r.get("subdir")) != (src["name"], src["subdir"])
        ]
        rows.append(
            {
                "name": src["name"],
                "kind": src["kind"],
                "origin": src["origin"],
                "subdir": src["subdir"],
                **_source_stats(dest_root, src),
                "skipped": src["skipped"],
            }
        )
        bucket["sources"] = sorted(rows, key=lambda r: (r["name"], r["subdir"]))
    manifest["exported_at"] = datetime.now(timezone.utc).isoformat()
    return manifest


# --------------------------------------------------------------- ingest: model

# 6: Claude Workflow agents are subagents, and a response's usage counts once.
# 7: a Claude SessionStart hook's additionalContext is a `system` row.
# 8: `raw` is no longer stored; sessions carry a content `fingerprint`.
# 9: the fingerprint hashes parsed fields, so a workflow agent's two logs are one session.
#    dsh session.v4 tool results (message-level toolCallId) get their text and links.
PARSER_VERSION = 9

# Migrations keyed on PRAGMA user_version (SQLITE-008). MIGRATIONS[0] is the
# schema as of 0.6.3, idempotent for a database that already has it.
MIGRATIONS: list[list[str]] = [
    [
        "CREATE TABLE IF NOT EXISTS files ("
        " id INTEGER PRIMARY KEY, harness TEXT NOT NULL,"
        " relpath TEXT NOT NULL UNIQUE, size INTEGER NOT NULL,"
        " mtime INTEGER NOT NULL, parser_version INTEGER NOT NULL,"
        " status TEXT NOT NULL, error TEXT, parsed_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS sessions ("
        " id INTEGER PRIMARY KEY, harness TEXT NOT NULL, native_id TEXT NOT NULL,"
        " file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,"
        " cwd TEXT, project_key TEXT, kind TEXT NOT NULL, parent_native_id TEXT,"
        " started_at TEXT, ended_at TEXT, model TEXT, title TEXT)",
        "CREATE TABLE IF NOT EXISTS messages ("
        " id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL"
        " REFERENCES sessions(id) ON DELETE CASCADE, ord INTEGER NOT NULL,"
        " native_id TEXT, parent_native_id TEXT, on_main_path INTEGER NOT NULL,"
        " role TEXT NOT NULL, ts TEXT, text TEXT NOT NULL, model TEXT,"
        " stop_reason TEXT, input_tokens INTEGER, output_tokens INTEGER,"
        " raw TEXT NOT NULL, injected INTEGER NOT NULL DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS tool_calls ("
        " id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL"
        " REFERENCES messages(id) ON DELETE CASCADE, call_id TEXT NOT NULL,"
        " name TEXT, arguments TEXT, result_message_id INTEGER"
        " REFERENCES messages(id) ON DELETE CASCADE, is_error INTEGER)",
        "CREATE INDEX IF NOT EXISTS sessions_file_id ON sessions(file_id)",
        "CREATE INDEX IF NOT EXISTS messages_session_id ON messages(session_id)",
        "CREATE INDEX IF NOT EXISTS tool_calls_message_id ON tool_calls(message_id)",
        "CREATE INDEX IF NOT EXISTS tool_calls_call_id ON tool_calls(call_id)",
        "CREATE INDEX IF NOT EXISTS tool_calls_result_message_id"
        " ON tool_calls(result_message_id)",
        "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts"
        " USING fts5(text, content='messages', content_rowid='id')",
        "CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN"
        " INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text); END",
        "CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN"
        " INSERT INTO messages_fts(messages_fts, rowid, text) VALUES"
        " ('delete', old.id, old.text); END",
        "CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE ON messages BEGIN"
        " INSERT INTO messages_fts(messages_fts, rowid, text) VALUES"
        " ('delete', old.id, old.text);"
        " INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text); END",
    ],
    # v2: denormalized columns + annotate/stats covering indexes. norm_key is
    # populated at insert; a pre-existing database must be rebuilt
    # (`ingest --rebuild`) or annotate() raises its guard.
    [
        "ALTER TABLE messages ADD COLUMN norm_key TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE messages ADD COLUMN harness TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE tool_calls ADD COLUMN harness TEXT NOT NULL DEFAULT ''",
        "CREATE INDEX IF NOT EXISTS messages_norm_session"
        " ON messages(norm_key, session_id)",
        "CREATE INDEX IF NOT EXISTS messages_role ON messages(role)",
        "CREATE INDEX IF NOT EXISTS messages_injected ON messages(injected)",
        "CREATE INDEX IF NOT EXISTS messages_harness ON messages(harness)",
        "CREATE INDEX IF NOT EXISTS tool_calls_harness ON tool_calls(harness)",
    ],
    # v3: prompt-cache token counts. Every harness reports input_tokens exclusive
    # of the cache; PARSER_VERSION 5 re-parses old rows so these fill in place.
    [
        "ALTER TABLE messages ADD COLUMN cache_read_tokens INTEGER",
        "ALTER TABLE messages ADD COLUMN cache_write_tokens INTEGER",
    ],
    # v4: what a generation was built with (schema_version, parser_version,
    # built_at); a mismatch makes the next ingest a full build.
    [
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    ],
    # v5: the original record is no longer copied into the index (the raw cache
    # holds it); the duplicate check compares a per-session fingerprint instead.
    [
        "ALTER TABLE messages DROP COLUMN raw",
        "ALTER TABLE sessions ADD COLUMN fingerprint TEXT NOT NULL DEFAULT ''",
        "CREATE INDEX sessions_harness_native ON sessions(harness, native_id)",
    ],
    # v6: per-row FTS triggers made a large insert crawl; `fts` builds the index in
    # one pass and an incremental ingest updates it in one batch (meta fts_max_id).
    [
        "DROP TRIGGER messages_fts_ai",
        "DROP TRIGGER messages_fts_ad",
        "DROP TRIGGER messages_fts_au",
    ],
]


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply pending MIGRATIONS steps; each step and its version bump commit together."""
    while True:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > len(MIGRATIONS):
            raise RuntimeError(
                f"transcripts.db is at schema {version}, newer than this code"
            )
        if version == len(MIGRATIONS):
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {version + 1:d}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id             INTEGER PRIMARY KEY,
    harness        TEXT NOT NULL,
    relpath        TEXT NOT NULL UNIQUE,
    size           INTEGER NOT NULL,
    mtime          INTEGER NOT NULL,
    parser_version INTEGER NOT NULL,
    status         TEXT NOT NULL,
    error          TEXT,
    parsed_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id               INTEGER PRIMARY KEY,
    harness          TEXT NOT NULL,
    native_id        TEXT NOT NULL,
    file_id          INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    cwd              TEXT,
    project_key      TEXT,
    kind             TEXT NOT NULL,
    parent_native_id TEXT,
    started_at       TEXT,
    ended_at         TEXT,
    model            TEXT,
    title            TEXT,
    fingerprint      TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS messages (
    id               INTEGER PRIMARY KEY,
    session_id       INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    ord              INTEGER NOT NULL,
    native_id        TEXT,
    parent_native_id TEXT,
    on_main_path     INTEGER NOT NULL,
    role             TEXT NOT NULL,
    ts               TEXT,
    text             TEXT NOT NULL,
    model            TEXT,
    stop_reason      TEXT,
    input_tokens     INTEGER,
    output_tokens    INTEGER,
    injected         INTEGER NOT NULL DEFAULT 0,
    norm_key         TEXT NOT NULL DEFAULT '',
    harness          TEXT NOT NULL DEFAULT '',
    cache_read_tokens  INTEGER,
    cache_write_tokens INTEGER
);
CREATE TABLE IF NOT EXISTS tool_calls (
    id                INTEGER PRIMARY KEY,
    message_id        INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    call_id           TEXT NOT NULL,
    name              TEXT,
    arguments         TEXT,
    result_message_id INTEGER REFERENCES messages(id) ON DELETE CASCADE,
    is_error          INTEGER,
    harness           TEXT NOT NULL DEFAULT ''
);
-- Result linking and cascade deletes look rows up by these; without them each
-- UPDATE scans the table and a large file inserts in minutes instead of seconds.
CREATE INDEX IF NOT EXISTS sessions_file_id ON sessions(file_id);
CREATE INDEX IF NOT EXISTS sessions_harness_native ON sessions(harness, native_id);
CREATE INDEX IF NOT EXISTS messages_session_id ON messages(session_id);
CREATE INDEX IF NOT EXISTS tool_calls_message_id ON tool_calls(message_id);
CREATE INDEX IF NOT EXISTS tool_calls_call_id ON tool_calls(call_id);
CREATE INDEX IF NOT EXISTS tool_calls_result_message_id ON tool_calls(result_message_id);
-- annotate groups by (norm_key, session_id) and stats counts by harness; these
-- covering indexes keep both off the big text column.
CREATE INDEX IF NOT EXISTS messages_norm_session ON messages(norm_key, session_id);
CREATE INDEX IF NOT EXISTS messages_role ON messages(role);
CREATE INDEX IF NOT EXISTS messages_injected ON messages(injected);
CREATE INDEX IF NOT EXISTS messages_harness ON messages(harness);
CREATE INDEX IF NOT EXISTS tool_calls_harness ON tool_calls(harness);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
    USING fts5(text, content='messages', content_rowid='id');
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments: str  # JSON text


@dataclass
class Message:
    ord: int
    native_id: str | None
    parent_native_id: str | None
    on_main_path: bool
    role: str  # user | assistant | tool_result | system
    ts: str | None
    text: str
    model: str | None
    stop_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    injected: bool = False
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)  # assistant only
    results: list[tuple[str, bool]] = field(default_factory=list)  # tool_result only


@dataclass
class Session:
    native_id: str
    cwd: str | None = None
    project_key: str | None = None
    kind: str = "main"  # main | subagent
    parent_native_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    model: str | None = None
    title: str | None = None
    fingerprint: str = ""


@dataclass
class ParsedFile:
    session: Session
    messages: list[Message]


def open_db(dest_root: Path) -> sqlite3.Connection:
    """Open the live index (`transcripts.db`, a symlink to the current generation)."""
    return _connect(dest_root / "transcripts.db")


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a database, migrate it to the current schema, and set per-connection pragmas.

    The pragmas (SQLITE-001..004, 012) are per-connection and do not persist in
    the file, so every connection sets them. WAL and the migration steps come
    first: the old schema was created without a user_version, so _migrate also
    builds a fresh database (MIGRATIONS[0] then [1]).
    """
    conn = sqlite3.connect(db_path, timeout=5.0)
    # WAL is a property of the file and persists, but the returned mode must be
    # checked: SQLite silently keeps the old mode where WAL can't work.
    mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    if mode != "wal":
        conn.close()
        raise RuntimeError(f"transcripts.db journal_mode is {mode!r}, not 'wal'")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA cache_size=-65536")
    conn.execute("PRAGMA temp_store=MEMORY")
    _migrate(conn)
    # The documented first-open call; 0x10000 checks every table, and running it
    # after a migration also covers the schema change's new indexes.
    conn.execute("PRAGMA optimize = 0x10002")
    return conn


_DSH_LOG_NAME = re.compile(r"session(?:\.v(\d+))?\.jsonl\.zstd")


def iter_raw_files(dest_root: Path) -> list[tuple[str, Path]]:
    """Every raw transcript file under the cache root, as (harness, path), sorted."""
    raw = dest_root / "raw"
    found: list[tuple[str, Path]] = []
    for harness, pattern in (
        ("claude", "*/**/*.jsonl"),
        ("pi", "*/**/*.jsonl"),
    ):
        found += [(harness, p) for p in (raw / harness).glob(pattern) if p.is_file()]
    # Each dsh format upgrade rewrites a session's whole history into a new
    # session.vN.jsonl.zstd beside the older logs; only the newest is indexed.
    newest: dict[Path, tuple[int, Path]] = {}
    for p in (raw / "dsh").glob("*/sessions/*/*/session*.jsonl.zstd"):
        if not p.is_file():
            continue
        m = _DSH_LOG_NAME.fullmatch(p.name)
        if m is None:
            raise ValueError(f"unknown dsh session log name: {p}")
        version = int(m.group(1) or 0)  # the legacy session.jsonl.zstd is version 0
        if p.parent not in newest or version > newest[p.parent][0]:
            newest[p.parent] = (version, p)
    found += [("dsh", p) for _, p in newest.values()]
    return sorted(found, key=lambda row: (row[0], str(row[1])))


def to_iso(ms: int) -> str:
    """Epoch milliseconds -> `YYYY-MM-DDTHH:MM:SS.mmmZ` (the stored timestamp shape)."""
    dt = datetime.fromtimestamp(ms / 1000, timezone.utc)
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond // 1000:03d}Z"


# ------------------------------------------------------------- ingest: parsers


def _blocks_text(content) -> str:
    """Text blocks only, joined by newlines. A plain string is one block."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        b.get("text") or ""
        for b in content
        if isinstance(b, dict) and b.get("type") == "text"
    )


def _mark_main_path(messages: list[Message]) -> None:
    """Walk from the last record up via parent ids; every id visited is on the path."""
    if not messages:
        return
    by_id = {m.native_id: m for m in messages if m.native_id}
    seen: set[str] = set()  # a self-referencing parent id must not loop forever
    cur: Message | None = messages[-1]
    while cur is not None and cur.native_id not in seen:
        cur.on_main_path = True
        if cur.native_id:
            seen.add(cur.native_id)
        cur = by_id.get(cur.parent_native_id) if cur.parent_native_id else None


def _finalize(session: Session, messages: list[Message]) -> ParsedFile:
    """Session span, model and fingerprint derive from the messages."""
    if messages:
        # Parsed fields, not the raw lines: Claude logs a workflow agent twice, and
        # the copies differ only in per-line metadata (version, entrypoint, usage).
        ends = [(m.native_id, m.role, m.ts, m.text) for m in (messages[0], messages[-1])]
        evidence = json.dumps([len(messages), ends])
        session.fingerprint = hashlib.sha256(evidence.encode()).hexdigest()
    stamps = [m.ts for m in messages if m.ts]
    session.started_at = stamps[0] if stamps else None
    session.ended_at = stamps[-1] if stamps else None
    models = [m.model for m in messages if m.role == "assistant" and m.model]
    session.model = models[-1] if models else None
    return ParsedFile(session=session, messages=messages)


def _json_lines(path: Path) -> list[str]:
    """Non-empty lines split on newline only — never str.splitlines(), which also
    breaks on U+2028 and friends that appear inside JSON strings. A final line that
    is not valid JSON is a write torn by a crash and is dropped, as for dsh."""
    lines = [line for line in path.read_text().split("\n") if line.strip()]
    if lines:
        try:
            json.loads(lines[-1])
        except json.JSONDecodeError:
            lines.pop()
    return lines


def _session_start_contexts(att) -> list[str]:
    """The additionalContext strings a SessionStart hook injected, else [].

    A strict allowlist: other hook attachments (PostToolUse repeats the whole tool
    output) and a hook's raw stdout/stderr are never indexed."""
    if not isinstance(att, dict) or att.get("hookEvent") != "SessionStart":
        return []
    found: list = []
    if att.get("type") == "hook_success":
        try:
            out = json.loads(att.get("stdout") or "")
        except (json.JSONDecodeError, TypeError):
            return []
        hso = out.get("hookSpecificOutput") if isinstance(out, dict) else None
        if isinstance(hso, dict):
            found = [hso.get("additionalContext")]
    elif att.get("type") == "hook_additional_context":
        # content is a list of strings (one per hook); a lone string is one entry
        for value in (att.get("additionalContext"), att.get("content")):
            found += value if isinstance(value, list) else [value]
    return [s for s in found if isinstance(s, str) and s.strip()]


def parse_claude(path: Path, relpath: str) -> ParsedFile:
    """One JSONL per session; `<session>/subagents/**/<name>.jsonl` are its subagents
    (Workflow agents sit at `subagents/workflows/<run>/agent-<id>.jsonl`)."""
    parts = Path(relpath).parts
    project_key = None
    if "projects" in parts and parts.index("projects") + 1 < len(parts):
        project_key = parts[parts.index("projects") + 1]
    # The file name is the session id for a main session and the agent id for a subagent.
    session = Session(native_id=path.stem, project_key=project_key)
    if "subagents" in parts:
        session.kind = "subagent"
        # The session that owns `subagents/` is the directory just above it.
        idx = len(parts) - 1 - parts[::-1].index("subagents")
        session.parent_native_id = parts[idx - 1]

    messages: list[Message] = []
    rows_by_response: dict[str, list[Message]] = {}
    contexts_seen: set[str] = set()  # hook_success and hook_additional_context repeat it
    for line in _json_lines(path):
        rec = json.loads(line)
        rtype = rec.get("type")
        if rtype == "ai-title":
            session.title = rec.get("title")
            continue
        if rtype == "attachment":
            att = rec.get("attachment")
            for text in _session_start_contexts(att):
                if text in contexts_seen:
                    continue
                contexts_seen.add(text)
                messages.append(
                    Message(
                        ord=len(messages),
                        native_id=rec.get("uuid"),
                        parent_native_id=rec.get("parentUuid"),
                        on_main_path=False,
                        role="system",
                        ts=rec.get("timestamp"),
                        text=text,
                        model=None,
                        stop_reason=None,
                        input_tokens=None,
                        output_tokens=None,
                        injected=True,
                    )
                )
            continue
        if rtype not in ("user", "assistant"):
            continue  # system, mode, attachment, … carry no conversation
        msg = rec.get("message") or {}
        content = msg.get("content")
        blocks = content if isinstance(content, list) else []
        calls: list[ToolCall] = []
        results: list[tuple[str, bool]] = []
        result_texts: list[str] = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                calls.append(
                    ToolCall(
                        call_id=b.get("id") or "",
                        name=b.get("name") or "",
                        arguments=json.dumps(b.get("input"), sort_keys=True),
                    )
                )
            elif b.get("type") == "tool_result":
                results.append((b.get("tool_use_id") or "", bool(b.get("is_error"))))
                # content is a plain string or text blocks; `<tool_use_error>…` is text too
                result_texts.append(_blocks_text(b.get("content")))
        if session.cwd is None:
            session.cwd = rec.get("cwd")
        is_result = rtype == "user" and bool(results)
        usage = msg.get("usage") or {}
        messages.append(
            Message(
                ord=len(messages),
                native_id=rec.get("uuid"),
                parent_native_id=rec.get("parentUuid"),
                on_main_path=False,
                role="tool_result" if is_result else rtype,
                ts=rec.get("timestamp"),
                text=(
                    # sibling text blocks sit beside the tool_result; keep both
                    "\n".join(t for t in (_blocks_text(content), *result_texts) if t)
                    if is_result
                    else _blocks_text(content)
                ),
                model=msg.get("model"),
                stop_reason=msg.get("stop_reason"),
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                cache_read_tokens=usage.get("cache_read_input_tokens"),
                cache_write_tokens=usage.get("cache_creation_input_tokens"),
                tool_calls=calls,
                results=results,
            )
        )
        if msg.get("id"):
            rows_by_response.setdefault(msg["id"], []).append(messages[-1])
    # A row per content block repeats its response's usage (early rows may hold partial
    # streaming counts): store each field's max once, on the response's last row.
    for rows in rows_by_response.values():
        for f in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
            seen = [getattr(r, f) for r in rows if getattr(r, f) is not None]
            for r in rows:
                setattr(r, f, None)
            setattr(rows[-1], f, max(seen) if seen else None)
    _mark_main_path(messages)
    return _finalize(session, messages)


def parse_pi(path: Path, relpath: str) -> ParsedFile:
    """Header line plus `message` entries; non-message entries are skipped."""
    lines = _json_lines(path)
    header = json.loads(lines[0]) if lines else {}
    if header.get("type") != "session":
        raise ValueError("pi session file does not start with a session header")
    if header.get("version") == 1:
        raise ValueError("pi session format v1 is unsupported")
    cwd = header.get("cwd")
    session = Session(
        native_id=header.get("id") or path.stem,
        cwd=cwd,
        project_key=cwd.replace("/", "-") if cwd else None,
    )
    parent = header.get("parentSession")
    if parent:
        session.kind = "subagent"
        # parentSession is a path; the parent session id follows the `_` in its file name.
        session.parent_native_id = Path(parent).stem.split("_", 1)[-1]

    model: str | None = None  # set by model_change for later messages that lack one
    messages: list[Message] = []
    for line in lines[1:]:
        rec = json.loads(line)
        rtype = rec.get("type")
        if rtype == "model_change":
            model = rec.get("modelId")
            continue
        if rtype == "session_info":
            session.title = rec.get("name")
            continue
        if rtype != "message":
            continue
        msg = rec.get("message") or {}
        role = msg.get("role")
        calls: list[ToolCall] = []
        results: list[tuple[str, bool]] = []
        if role == "toolResult":
            role = "tool_result"
            results.append((msg.get("toolCallId") or "", bool(msg.get("isError"))))
        content = msg.get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "toolCall":
                    calls.append(
                        ToolCall(
                            call_id=b.get("id") or "",
                            name=b.get("name") or "",
                            arguments=json.dumps(b.get("arguments"), sort_keys=True),
                        )
                    )
        usage = msg.get("usage") or {}
        messages.append(
            Message(
                ord=len(messages),
                native_id=rec.get("id"),
                parent_native_id=rec.get("parentId"),
                on_main_path=False,
                role=role or "user",
                ts=rec.get("timestamp"),
                text=_blocks_text(content),
                model=(msg.get("model") or model) if role == "assistant" else None,
                stop_reason=msg.get("stopReason"),
                input_tokens=usage.get("input"),
                output_tokens=usage.get("output"),
                cache_read_tokens=usage.get("cacheRead"),
                cache_write_tokens=usage.get("cacheWrite"),
                tool_calls=calls,
                results=results,
            )
        )
    _mark_main_path(messages)
    return _finalize(session, messages)


def decode_zstd_lines(path: Path):
    """Concatenated zstd frames -> complete lines, streamed; a truncated tail frame is dropped.

    A generator on purpose: a chunk-heavy dsh log decompresses to many times its size,
    so the whole text must never be held at once.
    """
    import zstandard

    buf = b""
    dctx = zstandard.ZstdDecompressor()
    with path.open("rb") as fh:
        with dctx.stream_reader(fh, read_across_frames=True) as reader:
            try:
                while True:
                    chunk = reader.read(1 << 20)
                    if not chunk:
                        break
                    buf += chunk
                    *complete, buf = buf.split(b"\n")
                    for raw in complete:
                        if raw.strip():
                            yield raw.decode("utf-8", errors="replace")
            except zstandard.ZstdError:
                pass  # truncated final frame: keep whatever decoded before it
    # Whatever is left never saw a newline: an incomplete last line, dropped.


DSH_EVENTS = ("user/message", "assistant/message", "tool/call", "tool/result")
# Cheap pre-filter so chunk rows are never JSON-parsed; tolerant of JSON spacing.
_DSH_KEEP = re.compile(
    r'"type":\s*"(?:' + "|".join(re.escape(t) for t in ("session", "session/title", *DSH_EVENTS)) + r')"'
)

# dsh's own bash tool never sets isError on a nonzero exit (verified against the
# live cache: 0 of 53,873 dsh bash results had is_error=1); it only appends this
# marker to the result text, and only on failure (no "[exit code: 0]" was ever
# observed either) — so it is the only signal for a failed bash command.
_DSH_BASH_EXIT_RE = re.compile(r"\[exit code:\s*(-?\d+)\]")


def _dsh_arguments(value) -> str:
    """dsh writes tool/call arguments as a JSON string; unwrap it once so the column
    holds the argument object like the other harnesses do."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            pass  # not JSON after all: keep the string, stored as a JSON string
    return json.dumps(value, sort_keys=True)


def parse_dsh(path: Path, relpath: str) -> ParsedFile:
    """Header frame plus seq-ordered event rows; chunk and control rows are dropped."""
    # Only rows whose type we keep are JSON-parsed; chunk rows dominate the log and
    # are discarded on the cheap prefix match instead.
    rows = [
        (line, json.loads(line))
        for line in decode_zstd_lines(path)
        if _DSH_KEEP.search(line)
    ]
    if not rows or rows[0][1].get("type") != "session":
        raise ValueError("dsh session file does not start with a session header")
    header = rows[0][1]
    session = Session(
        native_id=header.get("id") or path.parent.name,
        cwd=header.get("cwd"),
        project_key=path.parent.parent.name,
        kind="subagent" if header.get("origin") == "subagent" else "main",
        parent_native_id=header.get("parentSession"),
    )
    for _, rec in rows:
        if rec.get("type") == "session/title":
            session.title = (rec.get("data") or {}).get("title")

    events = [r for r in rows if r[1].get("type") in DSH_EVENTS]
    events.sort(key=lambda r: r[1].get("seq") or 0)
    messages: list[Message] = []
    last_assistant: Message | None = None
    for line, rec in events:
        data = rec.get("data") or {}
        rtype = rec.get("type")
        ts = to_iso(rec["time"]) if rec.get("time") else None
        if rtype == "tool/call":
            # tool/call rows are the source of truth; the assistant block may repeat one.
            if last_assistant is None:
                continue
            call_id = data.get("callId") or ""
            call = next(
                (c for c in last_assistant.tool_calls if c.call_id == call_id), None
            )
            if call is None:
                call = ToolCall(call_id=call_id, name="", arguments="")
                last_assistant.tool_calls.append(call)
            call.name = data.get("name") or ""
            call.arguments = _dsh_arguments(data.get("arguments"))
            continue

        msg = data if rtype == "user/message" else (data.get("message") or {})
        calls: list[ToolCall] = []
        results: list[tuple[str, bool]] = []
        text = _blocks_text(msg.get("content"))
        if rtype == "assistant/message":
            for b in msg.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "toolCall":
                    calls.append(
                        ToolCall(
                            call_id=b.get("id") or "",
                            name=b.get("name") or "",
                            arguments=json.dumps(b.get("arguments"), sort_keys=True),
                        )
                    )
        elif rtype == "tool/result":
            # v3 nests tool-result blocks in the message; v4's message is the result
            # itself (toolCallId, isError and text blocks at the message level).
            blocks = [
                b for b in msg.get("content") or []
                if isinstance(b, dict) and b.get("type") in ("tool-result", "toolResult")
            ]
            if not blocks and msg.get("toolCallId"):
                blocks = [msg]
            texts = []
            for b in blocks:
                call_id = b.get("toolCallId") or ""
                block_text = _blocks_text(b.get("content"))
                # data.error is the row-level failure; seen only with isError so far
                is_error = bool(b.get("isError")) or bool(data.get("error"))
                if not is_error and last_assistant is not None:
                    call = next(
                        (c for c in last_assistant.tool_calls if c.call_id == call_id),
                        None,
                    )
                    if call is not None and call.name == "bash":
                        codes = _DSH_BASH_EXIT_RE.findall(block_text)
                        if codes and int(codes[-1]) != 0:
                            is_error = True
                results.append((call_id, is_error))
                texts.append(block_text)
            text = "\n".join(t for t in texts if t)
        source = msg.get("source") or {}
        usage = data.get("usage") or {}
        message = Message(
            ord=len(messages),
            native_id=msg.get("id"),
            parent_native_id=None,  # dsh files carry no intra-file tree
            on_main_path=True,
            role={"user/message": "user", "assistant/message": "assistant"}.get(
                rtype, "tool_result"
            ),
            ts=ts,
            text=text,
            model=source.get("model"),
            stop_reason=(
                ((source.get("replayState") or {}).get("response") or {}).get(
                    "stopReason"
                )
            ),
            input_tokens=usage.get("inputTokens"),
            output_tokens=usage.get("outputTokens"),
            cache_read_tokens=usage.get("cacheReadTokens"),
            cache_write_tokens=usage.get("cacheWriteTokens"),
            tool_calls=calls,
            results=results,
        )
        messages.append(message)
        if rtype == "assistant/message":
            last_assistant = message
    return _finalize(session, messages)


PARSERS = {"claude": parse_claude, "pi": parse_pi, "dsh": parse_dsh}


# --------------------------------------------------------------- ingest: write


def _record_file(conn, harness: str, relpath: str, st, status: str, error) -> int:
    """Replace the file's row; the cascade drops the sessions parsed from it before."""
    _fts_forget(conn, [relpath])
    conn.execute("DELETE FROM files WHERE relpath = ?", (relpath,))
    cur = conn.execute(
        "INSERT INTO files (harness, relpath, size, mtime, parser_version, status,"
        " error, parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            harness,
            relpath,
            st.st_size,
            int(st.st_mtime),
            PARSER_VERSION,
            status,
            error,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    return cur.lastrowid


def _duplicate_session_id(conn, harness: str, native_id: str, parsed: ParsedFile) -> int | None:
    """The id of an existing (harness, native_id) session whose CONTENT matches
    `parsed`, if any — the same fingerprint (message count and first/last original
    record).

    A bare native_id match is not enough to call two sessions duplicates: a
    subagent tool can give its own log a generic filename (e.g. a workflow's
    `journal.jsonl`), and that filename becomes its native_id too, so unrelated
    workflow runs collide on it. Treating that collision as a duplicate would
    silently drop real, distinct content — the opposite of what this function
    exists to prevent. A byte-identical alias copy (two host project
    directories aliasing the same repo checkout) matches on all of these; a
    coincidental id collision between different real content will not.
    """
    row = conn.execute(
        "SELECT id FROM sessions WHERE harness = ? AND native_id = ? AND fingerprint = ?"
        " LIMIT 1",
        (harness, native_id, parsed.session.fingerprint),
    ).fetchone()
    return row[0] if row else None


def _insert_parsed(conn, file_id: int, harness: str, parsed: ParsedFile) -> bool:
    """Insert the parsed session, its messages and tool calls. Returns False (and
    inserts nothing) when a session with matching CONTENT for (harness, native_id)
    already exists under a different file — see `_duplicate_session_id`.

    Two host project directories can alias the same repo checkout — e.g. a plain
    symlink and a dotted one both pointing at the same clone — each holding a
    byte-identical copy of the same session file, and export has no way to tell
    they are the same repo. `_record_file` has already dropped this file's own
    prior session via cascade, so a matching row still present here belongs to
    another file. Keeping exactly one row per (harness, native_id) for TRUE
    duplicates is what lets an already-duplicated database heal on the next
    `ingest` (no `--rebuild` needed): bumping PARSER_VERSION forces every
    duplicate file to be re-parsed, and whichever one is processed last in this
    run keeps its session — the two copies are identical content, so which
    survives does not matter, only that exactly one does.
    """
    s = parsed.session
    if _duplicate_session_id(conn, harness, s.native_id, parsed) is not None:
        return False
    cur = conn.execute(
        "INSERT INTO sessions (harness, native_id, file_id, cwd, project_key, kind,"
        " parent_native_id, started_at, ended_at, model, title, fingerprint)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            harness,
            s.native_id,
            file_id,
            s.cwd,
            s.project_key,
            s.kind,
            s.parent_native_id,
            s.started_at,
            s.ended_at,
            s.model,
            s.title,
            s.fingerprint,
        ),
    )
    session_id = cur.lastrowid
    # SQLite would reuse the ids of a re-parsed file's deleted rows, which sit at the
    # top; ids at or below fts_max_id must never be reused, or the next FTS batch
    # (`id > fts_max_id`) misses the new rows.
    first_id = max(
        conn.execute("SELECT coalesce(max(id), 0) FROM messages").fetchone()[0],
        _fts_max_id(conn) or 0,
    ) + 1
    # Ids are assigned here, so each result's message id is known before any insert
    # and a tool call goes in already linked. As the per-result UPDATE did, a call
    # takes the last result naming its call id, anywhere in the session.
    results: dict[str, tuple[int, int]] = {}
    for i, m in enumerate(parsed.messages):
        for call_id, is_error in m.results:
            results[call_id] = (first_id + i, int(is_error))
    conn.executemany(
        "INSERT INTO messages (id, session_id, ord, native_id, parent_native_id,"
        " on_main_path, role, ts, text, model, stop_reason, input_tokens,"
        " output_tokens, injected, norm_key, harness, cache_read_tokens,"
        " cache_write_tokens)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                first_id + i,
                session_id,
                m.ord,
                m.native_id,
                m.parent_native_id,
                int(m.on_main_path),
                m.role,
                m.ts,
                m.text,
                m.model,
                m.stop_reason,
                m.input_tokens,
                m.output_tokens,
                int(m.injected),
                _norm_key(m.text),
                harness,
                m.cache_read_tokens,
                m.cache_write_tokens,
            )
            for i, m in enumerate(parsed.messages)
        ],
    )
    conn.executemany(
        "INSERT INTO tool_calls (message_id, call_id, name, arguments, harness,"
        " result_message_id, is_error) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (first_id + i, c.call_id, c.name, c.arguments, harness,
             *results.get(c.call_id, (None, None)))
            for i, m in enumerate(parsed.messages)
            for c in m.tool_calls
        ],
    )
    return True


class LockBusy(Exception):
    """Another process holds `<dest>/ingest.lock`."""

    def __init__(self, pid: str):
        super().__init__(f"another ingest is running (pid {pid})")


@contextlib.contextmanager
def ingest_lock(dest_root: Path):
    """Exclusive, non-blocking flock on `<dest>/ingest.lock`. The kernel drops it when
    the holder exits or crashes, so there is never a stale lock to clean up."""
    fd = os.open(dest_root / "ingest.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = os.pread(fd, 32, 0).decode(errors="replace").strip()
            raise LockBusy(holder or "?") from None
        # Truncate only once held, so a refused run never erases the holder's pid.
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{os.getpid()}\n".encode(), 0)
        yield
    finally:
        os.close(fd)


@dataclass
class IngestResult:
    parsed: int
    unchanged: int
    errors: int
    duplicates: int
    removed: int


def needs_full_build(dest_root: Path) -> bool:
    """True when there is no index, its schema is older than this code, or it was
    built by another PARSER_VERSION (every file would be re-parsed anyway). A newer
    schema raises: copies of the module at different versions must never rebuild
    over each other."""
    db_path = dest_root / "transcripts.db"
    if not db_path.exists():
        return True
    conn = sqlite3.connect(db_path, timeout=5.0)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > len(MIGRATIONS):
            raise RuntimeError(
                f"transcripts.db is at schema {version}, newer than this code"
            )
        if version < len(MIGRATIONS):
            return True
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'parser_version'"
        ).fetchone()
    finally:
        conn.close()
    return row is None or row[0] != str(PARSER_VERSION)


def full_build(dest_root: Path) -> IngestResult:
    """Build a new generation under `gens/`, then swap the `transcripts.db` symlink onto
    it in one rename. Readers that opened the old generation keep reading it; readers
    opened after the swap see the new one. The live file is never written."""
    gens = dest_root / "gens"
    gens.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"transcripts-{stamp}.db"
    n = 0
    while (gens / name).exists():  # a second build within the same second
        n += 1
        name = f"transcripts-{stamp}-{n}.db"
    conn = _connect(gens / name)
    # The big tables load without their secondary indexes, which are built once at the
    # end; the sessions indexes stay, the duplicate check looks sessions up by them.
    secondary = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
        " AND tbl_name IN ('messages', 'tool_calls')"
    ).fetchall()
    for index_name, _ in secondary:
        conn.execute(f"DROP INDEX {index_name}")
    result = _ingest_files(conn, dest_root, files_per_commit=200)
    t0 = time.monotonic()
    for _, sql in secondary:
        conn.execute(sql)
    conn.commit()
    print(f"timing: indexes={time.monotonic() - t0:.1f}s", file=sys.stderr)
    conn.close()
    # Finish the generation before it goes live, so no reader sees it un-annotated.
    _post_ingest(dest_root, gens / name, result)
    conn = _connect(gens / name)
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            [
                ("schema_version", str(len(MIGRATIONS))),
                ("parser_version", str(PARSER_VERSION)),
                ("built_at", datetime.now(timezone.utc).isoformat()),
            ],
        )
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    live = dest_root / "transcripts.db"
    was_plain_file = live.exists() and not live.is_symlink()
    link = dest_root / "transcripts.db.tmp-link"
    link.unlink(missing_ok=True)  # left by a run that crashed between these two lines
    link.symlink_to(Path("gens") / name)
    os.replace(link, live)
    keep = {name, f"{name}-wal", f"{name}-shm"}
    for f in gens.iterdir():
        if f.name not in keep:
            f.unlink()  # a reader still holding an old generation keeps it until it closes
    if was_plain_file:
        for suffix in ("-wal", "-shm"):
            (dest_root / f"transcripts.db{suffix}").unlink(missing_ok=True)
    # After the swap, so review never waits for it; searches refuse until it is done.
    build_fts(dest_root)
    return result


def ingest(dest_root: Path, rebuild: bool) -> IngestResult:
    """Under the lock: a full build into a new generation when `rebuild` or
    `needs_full_build`, else an incremental pass over the live one; then annotate.
    Raises LockBusy when another run holds the lock."""
    with ingest_lock(dest_root):
        if rebuild or needs_full_build(dest_root):
            return full_build(dest_root)
        conn = open_db(dest_root)
        result = _ingest_files(conn, dest_root, files_per_commit=1)
        _fts_add_new(conn)
        conn.close()
        _post_ingest(dest_root, dest_root / "transcripts.db", result)
    return result


def build_fts(dest_root: Path) -> None:
    """Rebuild `messages_fts` over every message of the live index in one pass and
    record the highest message id it covers. The caller holds the ingest lock."""
    t0 = time.monotonic()
    conn = open_db(dest_root)
    with conn:
        conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value)"
            " SELECT 'fts_max_id', coalesce(max(id), 0) FROM messages"
        )
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('fts_dirty', '0')")
    conn.close()
    print(f"timing: fts={time.monotonic() - t0:.1f}s", file=sys.stderr)


def _fts_max_id(conn) -> int | None:
    """The highest message id `messages_fts` covers, or None when the index has not
    been built or is marked dirty (then only `fts` can make it current)."""
    meta = dict(
        conn.execute("SELECT key, value FROM meta WHERE key IN ('fts_max_id', 'fts_dirty')")
    )
    if meta.get("fts_dirty") != "0" or "fts_max_id" not in meta:
        return None
    return int(meta["fts_max_id"])


def _mark_fts_dirty(conn, err: Exception) -> None:
    """A failed FTS update leaves the run successful; searches refuse until `fts` runs."""
    print(f"warning: full-text index update failed ({err!r}); run `fts`", file=sys.stderr)
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('fts_dirty', '1')")


def _fts_forget(conn, relpaths: list[str]) -> None:
    """Remove these files' indexed text before their rows are deleted: an
    external-content index needs the old text to remove it. Runs in the caller's
    transaction."""
    max_id = _fts_max_id(conn)
    if max_id is None or not relpaths:
        return
    try:
        conn.executemany(
            "INSERT INTO messages_fts(messages_fts, rowid, text)"
            " SELECT 'delete', m.id, m.text FROM messages m"
            " JOIN sessions s ON s.id = m.session_id JOIN files f ON f.id = s.file_id"
            " WHERE f.relpath = ? AND m.id <= ?",
            [(r, max_id) for r in relpaths],
        )
    except sqlite3.Error as e:
        _mark_fts_dirty(conn, e)


def _fts_add_new(conn) -> None:
    """Index the messages this run inserted (every id above fts_max_id) in one batch."""
    max_id = _fts_max_id(conn)
    if max_id is None:
        return
    t0 = time.monotonic()
    try:
        with conn:
            conn.execute(
                "INSERT INTO messages_fts(rowid, text) SELECT id, text FROM messages"
                " WHERE id > ?",
                (max_id,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value)"
                " SELECT 'fts_max_id', max(?, coalesce(max(id), 0)) FROM messages",
                (max_id,),
            )
    except sqlite3.Error as e:
        with conn:
            _mark_fts_dirty(conn, e)
    print(f"timing: fts_batch={time.monotonic() - t0:.1f}s", file=sys.stderr)


def _post_ingest(dest_root: Path, db_path: Path, result: IngestResult) -> None:
    """FTS merge and `injected` annotation for the database at `db_path`, after any
    run that parsed files."""
    if not result.parsed:
        return
    # Each incremental FTS batch adds a segment; a merge keeps searches fast.
    t0 = time.monotonic()
    conn = _connect(db_path)
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('optimize')")
    conn.commit()
    conn.close()
    t1 = time.monotonic()
    annotate(dest_root, db_path=db_path)
    print(
        f"timing: fts_optimize={t1 - t0:.1f}s annotate={time.monotonic() - t1:.1f}s",
        file=sys.stderr,
    )


def _ingest_files(
    conn: sqlite3.Connection, dest_root: Path, *, files_per_commit: int
) -> IngestResult:
    """Parse every new or changed raw file into `conn`'s database, committing after
    every `files_per_commit` files (an uncommitted batch is lost if the run fails)."""
    known = {
        row[0]: (row[1], row[2], row[3])
        for row in conn.execute(
            "SELECT relpath, size, mtime, parser_version FROM files"
        )
    }
    parsed_count = unchanged = errors = duplicates = 0
    raw_files = iter_raw_files(dest_root)
    # A row whose file left the indexed set (deleted, or a dsh log superseded by
    # a newer session.vN sibling) is stale; the cascade drops its sessions, so an
    # incremental run ends where --rebuild would.
    current = {path.relative_to(dest_root).as_posix() for _, path in raw_files}
    stale = [relpath for relpath in known if relpath not in current]
    with conn:
        _fts_forget(conn, stale)
        conn.executemany("DELETE FROM files WHERE relpath = ?", [(r,) for r in stale])
    start = last_progress = time.monotonic()
    parse_s = insert_s = 0.0
    pending = 0  # files written since the last commit
    for done, (harness, path) in enumerate(raw_files, 1):
        if pending >= files_per_commit:
            conn.commit()
            pending = 0
        now = time.monotonic()
        if now - last_progress >= PROGRESS_EVERY_S:
            last_progress = now
            elapsed = now - start
            print(
                f"progress: {done - 1}/{len(raw_files)} files"
                f" ({(done - 1) / elapsed:.1f}/s) elapsed={elapsed:.0f}s"
                f" parse={parse_s:.0f}s insert={insert_s:.0f}s",
                file=sys.stderr,
            )
        relpath = path.relative_to(dest_root).as_posix()
        st = path.stat()
        if known.get(relpath) == (st.st_size, int(st.st_mtime), PARSER_VERSION):
            unchanged += 1
            continue
        t0 = time.monotonic()
        try:
            parsed = PARSERS[harness](path, relpath)
        except Exception as e:  # one bad file is recorded, never stops the run
            _record_file(conn, harness, relpath, st, "error", repr(e))
            pending += 1
            errors += 1
            print(f"error: {relpath}: {e!r}", file=sys.stderr)
            continue
        t1 = time.monotonic()
        file_id = _record_file(conn, harness, relpath, st, "ok", None)
        pending += 1
        if not _insert_parsed(conn, file_id, harness, parsed):
            duplicates += 1
        t2 = time.monotonic()
        parse_s += t1 - t0
        insert_s += t2 - t1
        if t2 - t0 >= SLOW_FILE_S:
            print(
                f"slow: {relpath} parse={t1 - t0:.1f}s insert={t2 - t1:.1f}s"
                f" bytes={st.st_size} messages={len(parsed.messages)}"
                f" tool_calls={sum(len(m.tool_calls) for m in parsed.messages)}",
                file=sys.stderr,
            )
        parsed_count += 1
    conn.commit()
    print(
        f"ingest: parsed={parsed_count} unchanged={unchanged} errors={errors}"
        f" duplicates={duplicates} removed={len(stale)}"
    )
    print(
        f"timing: files={time.monotonic() - start:.1f}s parse={parse_s:.1f}s"
        f" insert={insert_s:.1f}s",
        file=sys.stderr,
    )
    return IngestResult(parsed_count, unchanged, errors, duplicates, len(stale))


def _norm_text(text: str) -> str:
    """Whitespace-collapsed, lowercased key for near-duplicate detection."""
    return " ".join(text.split()).lower()


def _norm_key(text: str) -> str:
    """A fixed-size digest of the normalized text; identical text ⇒ identical key.

    The normalized text of a large tool result can run to hundreds of KB, and
    storing it in the (norm_key, session_id) index made a rebuild crawl. A
    SHA-256 digest keeps the index at 64 bytes per row with the same grouping
    semantics (collisions are astronomically unlikely).
    """
    key = _norm_text(text)
    return hashlib.sha256(key.encode()).hexdigest() if key else ""


def annotate(
    dest_root: Path,
    min_sessions: int = 3,
    exclude_roles: tuple[str, ...] = ("tool_result",),
    *,
    db_path: Path | None = None,
) -> int:
    """Flag standing-instruction boilerplate as `injected` so a query can exclude it.

    A message is `injected` when it is a `system` message (the canonical injected
    context), or when its normalized text appears, outside the excluded roles, in
    `min_sessions` or more distinct sessions — the signature of a standing
    instruction the harness prepends to every session (e.g. the AGENTS.md
    "always check for a dev container first" rule). `tool_result` messages are
    excluded by default so a recurring *error* (identical text across sessions) is
    not mistaken for boilerplate and hidden from issue hunts.

    Idempotent: it recomputes from the index and writes only rows whose flag changed,
    so it can be re-run after any ingest. Returns the number of messages flagged. `db_path`
    defaults to the live index; a full build passes its new generation.
    """
    conn = _connect(db_path or dest_root / "transcripts.db")
    total = conn.execute("SELECT count(*) FROM messages").fetchone()[0]
    if total:
        populated = conn.execute(
            "SELECT count(*) FROM messages WHERE norm_key != ''"
        ).fetchone()[0]
        if populated == 0:
            conn.close()
            raise RuntimeError("run 'ingest --rebuild' to populate norm_key")
    role_clause = ""
    params: tuple = (min_sessions,)
    if exclude_roles:
        role_placeholders = ",".join("?" * len(exclude_roles))
        role_clause = f" AND role NOT IN ({role_placeholders})"
        # Placeholder order: inner group roles, HAVING min_sessions, outer roles.
        params = (*exclude_roles, min_sessions, *exclude_roles)
    # The norm_key / role / injected covering indexes keep every statement off
    # the big text column. Only rows whose flag changes are written.
    conn.execute("CREATE TEMP TABLE annotate_target (id INTEGER PRIMARY KEY)")
    conn.execute(
        f"INSERT INTO annotate_target SELECT id FROM messages WHERE norm_key IN ("
        f" SELECT norm_key FROM messages WHERE norm_key != ''{role_clause}"
        f" GROUP BY norm_key HAVING COUNT(DISTINCT session_id) >= ?)"
        f"{role_clause}",
        params,
    )
    flagged = conn.execute("SELECT count(*) FROM annotate_target").fetchone()[0]
    conn.execute(
        "INSERT OR IGNORE INTO annotate_target SELECT id FROM messages WHERE role = 'system'"
    )
    conn.execute(
        "UPDATE messages SET injected = 0 WHERE injected = 1"
        " AND id NOT IN (SELECT id FROM annotate_target)"
    )
    conn.execute(
        "UPDATE messages SET injected = 1 WHERE injected = 0"
        " AND id IN (SELECT id FROM annotate_target)"
    )
    conn.commit()
    conn.close()
    print(
        f"annotate: injected={flagged}"
        f" (min_sessions={min_sessions}, exclude_roles={','.join(exclude_roles)})"
    )
    return flagged


def stats(conn) -> str:
    """One table: files by status, sessions, messages and tool calls per harness."""
    header = ("harness", "files", "ok", "error", "sessions", "messages", "tool_calls")
    rows: list[tuple] = []
    for harness in HARNESSES:
        counts = dict(
            conn.execute(
                "SELECT status, count(*) FROM files WHERE harness = ? GROUP BY status",
                (harness,),
            )
        )
        rows.append(
            (
                harness,
                sum(counts.values()),
                counts.get("ok", 0),
                counts.get("error", 0),
                conn.execute(
                    "SELECT count(*) FROM sessions WHERE harness = ?", (harness,)
                ).fetchone()[0],
                # The denormalized harness columns make these covering-index
                # counts instead of per-row joins against the big tables.
                conn.execute(
                    "SELECT count(*) FROM messages WHERE harness = ?", (harness,)
                ).fetchone()[0],
                conn.execute(
                    "SELECT count(*) FROM tool_calls WHERE harness = ?", (harness,)
                ).fetchone()[0],
            )
        )
    rows.append(("total", *(sum(r[i] for r in rows) for i in range(1, len(header)))))
    widths = [max(len(str(r[i])) for r in (header, *rows)) for i in range(len(header))]
    out = []
    for row in (header, *rows):
        cells = [str(row[0]).ljust(widths[0])]
        cells += [str(c).rjust(widths[i + 1]) for i, c in enumerate(row[1:])]
        out.append("  ".join(cells).rstrip())
    return "\n".join(out)


# ------------------------------------------------------------------- commands


def cmd_export(args) -> int:
    dest_root = resolve_dest(args.dest)
    docker = "docker"
    if args.harness == "claude":
        sources = discover_claude(docker)
    elif args.harness == "pi":
        sources = discover_pi()
    else:
        sources = discover_dsh(docker)
    if not sources:
        print(f"no {args.harness} transcript sources found", file=sys.stderr)
    if not args.dry_run:
        dest_root.mkdir(parents=True, exist_ok=True)
    manifest = export_sources(dest_root, sources, args.dry_run, docker)
    if not args.dry_run:
        (dest_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if args.json:
        print(json.dumps(manifest, indent=2))
    return 0


def cmd_ingest(args) -> int:
    """0 when the run completed, even with parse errors (recorded in `files`); 75
    when another run holds the lock; any other failure raises (exit 1)."""
    try:
        result = ingest(resolve_dest(args.dest), args.rebuild)
    except LockBusy as e:
        print(e, file=sys.stderr)
        return 75
    if result.errors:
        print(
            f"errors: {result.errors} files failed to parse (see files.status='error')",
            file=sys.stderr,
        )
    return 0


def cmd_stats(args) -> int:
    conn = open_db(resolve_dest(args.dest))
    print(stats(conn))
    conn.close()
    return 0


def cmd_annotate(args) -> int:
    roles = tuple(args.exclude_role) if args.exclude_role else ("tool_result",)
    dest_root = resolve_dest(args.dest)
    try:
        with ingest_lock(dest_root):
            annotate(dest_root, args.min_sessions, roles)
            return 0  # never the flagged count: 75 means "lock busy"
    except LockBusy as e:
        print(e, file=sys.stderr)
        return 75


def cmd_fts(args) -> int:
    """Rebuild the full-text index of the live generation; 75 when the lock is held."""
    dest_root = resolve_dest(args.dest)
    try:
        with ingest_lock(dest_root):
            db_path = dest_root / "transcripts.db"
            version = 0
            if db_path.exists():
                conn = sqlite3.connect(db_path, timeout=5.0)
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                conn.close()
            if version < len(MIGRATIONS):
                # Opening would create or migrate the live file in place; ingest
                # builds a new generation instead.
                print("the index needs a full build first; run: transcripts.py ingest",
                      file=sys.stderr)
                return 1
            build_fts(dest_root)
            return 0
    except LockBusy as e:
        print(e, file=sys.stderr)
        return 75


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Export agent transcripts on-device and index them."
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export", help="copy raw transcripts into the cache")
    p_export.add_argument("harness", choices=list(HARNESSES))
    p_export.add_argument(
        "--dest", help="cache root (default $AGENT_TRANSCRIPT_DIR or the user cache dir)"
    )
    p_export.add_argument(
        "--dry-run", action="store_true", help="plan only, write nothing"
    )
    p_export.add_argument(
        "--json", action="store_true", help="also emit the manifest JSON to stdout"
    )
    p_export.set_defaults(func=cmd_export)

    p_ingest = sub.add_parser("ingest", help="build or refresh the sqlite index")
    p_ingest.add_argument("--dest", help="cache root")
    p_ingest.add_argument(
        "--rebuild",
        action="store_true",
        help="reparse everything into a new generation, then swap it in",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    p_stats = sub.add_parser("stats", help="summarize the cache and the index")
    p_stats.add_argument("--dest", help="cache root")
    p_stats.set_defaults(func=cmd_stats)

    p_annotate = sub.add_parser(
        "annotate", help="flag standing-instruction boilerplate as `injected`"
    )
    p_annotate.add_argument("--dest", help="cache root")
    p_annotate.add_argument(
        "--min-sessions",
        type=int,
        default=3,
        help="distinct sessions a normalized text must appear in to be flagged (default 3)",
    )
    p_annotate.add_argument(
        "--exclude-role",
        action="append",
        default=None,
        help="role the duplicate detector never flags (repeatable; default tool_result)",
    )
    p_annotate.set_defaults(func=cmd_annotate)

    p_fts = sub.add_parser("fts", help="rebuild the full-text index in one pass")
    p_fts.add_argument("--dest", help="cache root")
    p_fts.set_defaults(func=cmd_fts)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

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
    uv run --script transcripts.py ingest [--dest DIR] [--rebuild]
    uv run --script transcripts.py stats  [--dest DIR]
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HARNESSES = ("claude", "pi", "dsh")
DEFAULT_DEST_NAME = "agent-transcripts"

# Tier-3 name-pattern sweeps for orphaned volumes whose containers were deleted.
CLAUDE_VOLUME_PATTERNS = ("claude-code-config-*", "*-claude-*")
DSH_VOLUME_PATTERNS = ("*deepseek*",)


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
    skipped = ["attachments/", "spill/"]
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


def _write_member(dest: Path, data: bytes, mtime: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    os.utime(dest, (mtime, mtime))  # preserve source mtime so incremental skip works


def _source_root(dest_root: Path, src: dict) -> Path:
    return dest_root / "raw" / src["harness"] / src["name"] / src["subdir"]


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
        if src["harness"] == "pi" and rel.parts[0] == "spill":
            continue  # pi's third-party spill payloads are out of scope in v0.1
        dest = base / rel
        st = f.stat()
        if should_copy(st.st_size, int(st.st_mtime), dest):
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)  # copy2 preserves mtime
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

PARSER_VERSION = 2

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
    title            TEXT
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
    raw              TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_calls (
    id                INTEGER PRIMARY KEY,
    message_id        INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    call_id           TEXT NOT NULL,
    name              TEXT,
    arguments         TEXT,
    result_message_id INTEGER REFERENCES messages(id) ON DELETE CASCADE,
    is_error          INTEGER
);
-- Result linking and cascade deletes look rows up by these; without them each
-- UPDATE scans the table and a large file inserts in minutes instead of seconds.
CREATE INDEX IF NOT EXISTS sessions_file_id ON sessions(file_id);
CREATE INDEX IF NOT EXISTS messages_session_id ON messages(session_id);
CREATE INDEX IF NOT EXISTS tool_calls_message_id ON tool_calls(message_id);
CREATE INDEX IF NOT EXISTS tool_calls_call_id ON tool_calls(call_id);
CREATE INDEX IF NOT EXISTS tool_calls_result_message_id ON tool_calls(result_message_id);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
    USING fts5(text, content='messages', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
END;
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
    raw: str
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


@dataclass
class ParsedFile:
    session: Session
    messages: list[Message]


def open_db(dest_root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(dest_root / "transcripts.db")
    conn.execute("PRAGMA foreign_keys=ON")
    # One commit per file: WAL + NORMAL keeps every committed file durable across a
    # process kill while avoiding a full fsync per file on a multi-GB first ingest.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def iter_raw_files(dest_root: Path) -> list[tuple[str, Path]]:
    """Every raw transcript file under the cache root, as (harness, path), sorted."""
    raw = dest_root / "raw"
    found: list[tuple[str, Path]] = []
    for harness, pattern in (
        ("claude", "*/**/*.jsonl"),
        ("pi", "*/**/*.jsonl"),
        ("dsh", "*/sessions/*/*/session.jsonl.zstd"),
    ):
        found += [(harness, p) for p in (raw / harness).glob(pattern) if p.is_file()]
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
    """Session span and model derive from the messages."""
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


def parse_claude(path: Path, relpath: str) -> ParsedFile:
    """One JSONL per session; `<session>/subagents/<name>.jsonl` are its subagents."""
    parts = Path(relpath).parts
    project_key = None
    if "projects" in parts and parts.index("projects") + 1 < len(parts):
        project_key = parts[parts.index("projects") + 1]
    # The file name is the session id for a main session and the agent id for a subagent.
    session = Session(native_id=path.stem, project_key=project_key)
    if path.parent.name == "subagents":
        session.kind = "subagent"
        session.parent_native_id = path.parent.parent.name

    messages: list[Message] = []
    for line in _json_lines(path):
        rec = json.loads(line)
        rtype = rec.get("type")
        if rtype == "ai-title":
            session.title = rec.get("title")
            continue
        if rtype not in ("user", "assistant"):
            continue  # system, mode, attachment, … carry no conversation
        msg = rec.get("message") or {}
        content = msg.get("content")
        blocks = content if isinstance(content, list) else []
        calls: list[ToolCall] = []
        results: list[tuple[str, bool]] = []
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
        if session.cwd is None:
            session.cwd = rec.get("cwd")
        usage = msg.get("usage") or {}
        messages.append(
            Message(
                ord=len(messages),
                native_id=rec.get("uuid"),
                parent_native_id=rec.get("parentUuid"),
                on_main_path=False,
                role="tool_result" if (rtype == "user" and results) else rtype,
                ts=rec.get("timestamp"),
                text=_blocks_text(content),
                model=msg.get("model"),
                stop_reason=msg.get("stop_reason"),
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                raw=line,
                tool_calls=calls,
                results=results,
            )
        )
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
                raw=line,
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
            call.arguments = json.dumps(data.get("arguments"), sort_keys=True)
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
            texts = []
            for b in msg.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "toolResult":
                    results.append((b.get("toolCallId") or "", bool(b.get("isError"))))
                    texts.append(_blocks_text(b.get("content")))
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
            raw=line,
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


def _insert_parsed(conn, file_id: int, harness: str, parsed: ParsedFile) -> None:
    s = parsed.session
    cur = conn.execute(
        "INSERT INTO sessions (harness, native_id, file_id, cwd, project_key, kind,"
        " parent_native_id, started_at, ended_at, model, title)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        ),
    )
    session_id = cur.lastrowid
    inserted: list[tuple[int, Message]] = []
    for m in parsed.messages:
        mcur = conn.execute(
            "INSERT INTO messages (session_id, ord, native_id, parent_native_id,"
            " on_main_path, role, ts, text, model, stop_reason, input_tokens,"
            " output_tokens, raw) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
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
                m.raw,
            ),
        )
        message_id = mcur.lastrowid
        inserted.append((message_id, m))
        for c in m.tool_calls:
            conn.execute(
                "INSERT INTO tool_calls (message_id, call_id, name, arguments)"
                " VALUES (?, ?, ?, ?)",
                (message_id, c.call_id, c.name, c.arguments),
            )
    # Link results to their calls once every message of the file exists.
    for message_id, m in inserted:
        for call_id, is_error in m.results:
            conn.execute(
                "UPDATE tool_calls SET result_message_id = ?, is_error = ?"
                " WHERE call_id = ? AND message_id IN"
                " (SELECT id FROM messages WHERE session_id = ?)",
                (message_id, int(is_error), call_id, session_id),
            )


def ingest(dest_root: Path, rebuild: bool) -> int:
    """Parse every new or changed raw file into the db. Returns the parse-error count."""
    db_path = dest_root / "transcripts.db"
    if rebuild and db_path.exists():
        db_path.unlink()
    conn = open_db(dest_root)
    known = {
        row[0]: (row[1], row[2], row[3])
        for row in conn.execute(
            "SELECT relpath, size, mtime, parser_version FROM files"
        )
    }
    parsed_count = unchanged = errors = 0
    for harness, path in iter_raw_files(dest_root):
        relpath = path.relative_to(dest_root).as_posix()
        st = path.stat()
        if known.get(relpath) == (st.st_size, int(st.st_mtime), PARSER_VERSION):
            unchanged += 1
            continue
        try:
            parsed = PARSERS[harness](path, relpath)
        except Exception as e:  # one bad file is recorded, never stops the run
            with conn:
                _record_file(conn, harness, relpath, st, "error", repr(e))
            errors += 1
            print(f"error: {relpath}: {e!r}", file=sys.stderr)
            continue
        with conn:
            file_id = _record_file(conn, harness, relpath, st, "ok", None)
            _insert_parsed(conn, file_id, harness, parsed)
        parsed_count += 1
    conn.close()
    print(f"ingest: parsed={parsed_count} unchanged={unchanged} errors={errors}")
    return errors


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
                conn.execute(
                    "SELECT count(*) FROM messages m JOIN sessions s"
                    " ON s.id = m.session_id WHERE s.harness = ?",
                    (harness,),
                ).fetchone()[0],
                conn.execute(
                    "SELECT count(*) FROM tool_calls t JOIN messages m"
                    " ON m.id = t.message_id JOIN sessions s ON s.id = m.session_id"
                    " WHERE s.harness = ?",
                    (harness,),
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
    return ingest(resolve_dest(args.dest), args.rebuild)


def cmd_stats(args) -> int:
    conn = open_db(resolve_dest(args.dest))
    print(stats(conn))
    conn.close()
    return 0


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
        "--rebuild", action="store_true", help="delete the database and reparse"
    )
    p_ingest.set_defaults(func=cmd_ingest)

    p_stats = sub.add_parser("stats", help="summarize the cache and the index")
    p_stats.add_argument("--dest", help="cache root")
    p_stats.set_defaults(func=cmd_stats)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

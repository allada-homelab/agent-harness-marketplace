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
import shutil
import subprocess
import sys
import tarfile
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
        dest = base / f.relative_to(origin)
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
    print("ingest: not implemented", file=sys.stderr)
    return 2


def cmd_stats(args) -> int:
    print("stats: not implemented", file=sys.stderr)
    return 2


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

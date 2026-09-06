#!/usr/bin/env python3
"""Export Claude Code transcript JSONL to an on-device root, read-only + incremental.

Discovers transcripts from the host `~/.claude/projects` and from docker named
volumes used by dev containers, then copies them under
`~/.cache/claude-transcripts/<source>/projects/<slug>/*.jsonl` with a manifest.

Sources are never mutated: volume reads run in a throwaway `alpine` container with
the volume mounted `:ro`. The output root must never be inside a git worktree.
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

# Tier-3 name-pattern sweep for orphaned volumes whose containers were deleted.
VOLUME_PATTERNS = ("claude-code-config-*", "*-claude-*")
DEFAULT_DEST = Path.home() / ".cache" / "claude-transcripts"


def _config_projects_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    root = Path(base).expanduser() if base else Path.home() / ".claude"
    return root / "projects"


def resolve_dest(cli_dest: str | None) -> Path:
    """CLI --dest > $CLAUDE_TRANSCRIPT_DIR > ~/.cache/claude-transcripts, then guard."""
    if cli_dest:
        dest = Path(cli_dest).expanduser()
    elif os.environ.get("CLAUDE_TRANSCRIPT_DIR"):
        dest = Path(os.environ["CLAUDE_TRANSCRIPT_DIR"]).expanduser()
    else:
        dest = DEFAULT_DEST
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
            "(transcripts must never enter a repo; set $CLAUDE_TRANSCRIPT_DIR elsewhere)"
        )


def discover_sources(docker: str = "docker") -> list[dict]:
    """Three tiers, deduped by volume name. Docker absent/erroring → host only."""
    sources: list[dict] = []
    projects = _config_projects_dir()
    if projects.is_dir():
        sources.append({"kind": "host", "name": "host", "origin": str(projects)})

    volumes: dict[str, dict] = {}
    if shutil.which(docker) is None:
        print(
            f"warning: {docker} not found; exporting host source only", file=sys.stderr
        )
        return sources

    # Tier 2: containers (running or stopped) with a mount destination ending in /.claude.
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
                        ).rstrip("/").endswith("/.claude"):
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
                if any(fnmatch.fnmatch(name, p) for p in VOLUME_PATTERNS):
                    volumes[name] = {
                        "kind": "volume",
                        "name": name,
                        "origin": "volume-sweep",
                    }
    except FileNotFoundError as e:
        print(f"warning: docker volume ls failed ({e}); continuing", file=sys.stderr)

    sources.extend(volumes.values())
    return sources


def _is_safe_member(name: str) -> bool:
    """Reject tar members that would escape the export root (path-traversal CVE class)."""
    parts = Path(name).parts
    return not (Path(name).is_absolute() or ".." in parts)


def should_copy(src_stat: dict, dest_path: Path) -> bool:
    """True unless dest exists with identical size and (integer) mtime."""
    if not dest_path.exists():
        return True
    st = dest_path.stat()
    return src_stat["size"] != st.st_size or src_stat["mtime"] != int(st.st_mtime)


def _write_member(dest: Path, data: bytes, mtime: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    os.utime(dest, (mtime, mtime))  # preserve source mtime so incremental skip works


def _export_host(src: dict, dest_root: Path, dry_run: bool) -> dict:
    projects = _config_projects_dir()
    copied = skipped = 0
    for f in sorted(projects.rglob("*.jsonl")):
        if not f.is_file():
            continue
        rel = f.relative_to(projects)
        dest = dest_root / "host" / "projects" / rel
        st = f.stat()
        if should_copy({"size": st.st_size, "mtime": int(st.st_mtime)}, dest):
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)  # copy2 preserves mtime
            copied += 1
        else:
            skipped += 1
    return {"copied": copied, "skipped": skipped}


def _export_volume(src: dict, dest_root: Path, dry_run: bool, docker: str) -> dict:
    name = src["name"]
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
            "projects",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            for member in tar:
                if not member.isfile() or not member.name.endswith(".jsonl"):
                    continue
                if not _is_safe_member(member.name):
                    skipped += 1
                    continue
                dest = dest_root / name / member.name
                if should_copy({"size": member.size, "mtime": int(member.mtime)}, dest):
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


def _source_stats(dest_root: Path, name: str) -> dict:
    """Aggregate the exported tree for one source: file count, bytes, newest mtime."""
    base = dest_root / name / "projects"
    files = 0
    total = 0
    newest = 0
    for f in base.rglob("*.jsonl"):
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
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"exported_at": None, "sources": []}


def _run(
    dest_root: Path, sources: list[dict], dry_run: bool, docker: str
) -> tuple[dict, list[dict]]:
    rows = []
    manifest = _load_manifest(dest_root)
    by_name = {s["name"]: s for s in manifest.get("sources", [])}
    for src in sources:
        if src["kind"] == "host":
            counts = _export_host(src, dest_root, dry_run)
        else:
            counts = _export_volume(src, dest_root, dry_run, docker)
        rows.append({**src, **counts})
        if not dry_run:
            stats = _source_stats(dest_root, src["name"])
            by_name[src["name"]] = {
                "name": src["name"],
                "kind": src["kind"],
                "origin": src["origin"],
                **stats,
            }
    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "sources": list(by_name.values()),
    }
    return manifest, rows


def _print_summary(rows: list[dict], dest_root: Path, dry_run: bool) -> None:
    print()
    header = f"{'source':40} {'copied':>8} {'skipped':>8} {'bytes':>12}"
    print(header)
    print("-" * len(header))
    for r in rows:
        b = (
            "-"
            if dry_run
            else str(
                sum(
                    f.stat().st_size
                    for f in (dest_root / r["name"] / "projects").rglob("*.jsonl")
                    if f.is_file()
                )
            )
        )
        print(f"{r['name'][:40]:40} {r['copied']:>8} {r['skipped']:>8} {b:>12}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Export Claude Code transcripts on-device."
    )
    ap.add_argument(
        "--dest",
        help="output root (default $CLAUDE_TRANSCRIPT_DIR or ~/.cache/claude-transcripts)",
    )
    ap.add_argument("--dry-run", action="store_true", help="plan only, write nothing")
    ap.add_argument(
        "--json", action="store_true", help="also emit manifest JSON to stdout"
    )
    args = ap.parse_args(argv)

    dest_root = resolve_dest(args.dest)
    docker = "docker"
    sources = discover_sources(docker)
    if not args.dry_run:
        dest_root.mkdir(parents=True, exist_ok=True)

    manifest, rows = _run(dest_root, sources, args.dry_run, docker)

    if not args.dry_run:
        (dest_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    _print_summary(rows, dest_root, args.dry_run)
    if args.json:
        print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

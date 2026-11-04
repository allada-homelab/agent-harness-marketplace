#!/usr/bin/env python3
"""Pin a domain's upstream sources and shard them for the rules-sweep workflow.

Usage:
    python3 -I prepare.py <domains/NAME.json> <work-dir> <rules-dir> [source=ref ...]

Each source in the descriptor is sparse-cloned into <work-dir>/src/<name> at its
ref: "latest-tag" (the highest <tag_prefix>X.Y.Z tag), "default" (the default
branch) or an explicit tag or branch, which a `source=ref` argument overrides.
The docs are then packed into shards of about TARGET_LINES; a longer file is
split into line ranges at blank lines. Prints the workflow's `args` as JSON.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

TARGET_LINES = 1800  # one reader can hold a shard this size and still quote line numbers
DOC_SUFFIXES = (".md", ".rst", ".json")


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def latest_tag(repo: str, prefix: str) -> str:
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)\.(\d+)\.(\d+)$")
    tags = []
    for line in git("ls-remote", "--tags", "--refs", repo).splitlines():
        m = pattern.match(line.split("refs/tags/", 1)[1])
        if m:
            tags.append((tuple(map(int, m.groups())), m.group(0)))
    if not tags:
        sys.exit(f"prepare.py: no {prefix}X.Y.Z tag in {repo}")
    return max(tags)[1]


def fetch(src: dict, dest: Path, ref: str) -> tuple[str, str]:
    if ref == "latest-tag":
        ref = latest_tag(src["repo"], src.get("tag_prefix", ""))
    clone = ["clone", "-q", "--filter=blob:none", "--no-checkout"]
    if not src.get("history"):
        clone += ["--depth", "1"]
    if ref != "default":
        clone += ["--branch", ref]
    git(*clone, src["repo"], str(dest))
    git("sparse-checkout", "set", "--no-cone", *(f"/{p}" for p in src["paths"]), cwd=dest)
    git("checkout", "-q", cwd=dest)
    if ref == "default":
        ref = git("rev-parse", "--abbrev-ref", "HEAD", cwd=dest)
    return ref, git("rev-parse", "HEAD", cwd=dest)


def doc_files(src: dict, dest: Path) -> list[Path]:
    found = []
    for p in src["paths"]:
        target = dest / p
        if target.is_file():
            found.append(target)
        elif target.is_dir():
            found += [f for f in target.rglob("*") if f.suffix in DOC_SUFFIXES]
        else:
            sys.exit(f"prepare.py: {src['name']}: path {p} is not in the checkout")
    excluded = tuple(src.get("exclude", []))
    return sorted(f for f in found if not f.relative_to(dest).as_posix().startswith(excluded))


def ranges(lines: list[str]) -> list[tuple[int, int]]:
    """1-based inclusive ranges of at most about TARGET_LINES, cut at a blank line."""
    out, start, n = [], 1, len(lines)
    while start <= n:
        end = min(start + TARGET_LINES - 1, n)
        if end < n:
            for cut in range(end, max(start, end - 200), -1):
                if not lines[cut - 1].strip():
                    end = cut
                    break
        out.append((start, end))
        start = end + 1
    return out


def main() -> None:
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    domain_file, work, rules_dir = Path(sys.argv[1]), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    overrides = dict(a.split("=", 1) for a in sys.argv[4:])
    domain = json.loads(domain_file.read_text())
    root = work / "src"
    root.mkdir(parents=True, exist_ok=True)

    sources, pieces, versions = [], [], {}
    for src in domain["sources"]:
        ref, sha = fetch(src, root / src["name"], overrides.pop(src["name"], src["ref"]))
        sources.append({"name": src["name"], "repo": src["repo"], "ref": ref, "sha": sha})
        versions[src["name"]] = ref.removeprefix(src.get("tag_prefix", ""))
        for f in doc_files(src, root / src["name"]):
            text = f.read_text(encoding="utf-8").splitlines()
            for start, end in ranges(text):
                pieces.append({"path": f.relative_to(root).as_posix(), "start": start, "end": end})
    if overrides:
        sys.exit(f"prepare.py: unknown source(s): {', '.join(overrides)}")

    shards, current, size = [], [], 0
    for piece in pieces:
        n = piece["end"] - piece["start"] + 1
        if current and size + n > TARGET_LINES:
            shards.append(current)
            current, size = [], 0
        current.append(piece)
        size += n
    shards.append(current)

    fill = lambda s: s.format(**versions)  # "{uv}" in a descriptor string becomes the pinned version
    json.dump({
        "domain": domain["domain"],
        "subject": domain["subject"],
        "out_of_scope": domain["out_of_scope"],
        "live": fill(domain["live"]),
        "floors": fill(domain["floors"]),
        "root": str(root),
        "sources": sources,
        "shards": [{"id": f"s{i:02d}", "files": files} for i, files in enumerate(shards, 1)],
        "topics": sorted(p.stem for p in (rules_dir / "references").glob("*.md")),
        "rulesDir": str(rules_dir),
        "outDir": str(work / "out"),
    }, sys.stdout, indent=1)
    print()


main()

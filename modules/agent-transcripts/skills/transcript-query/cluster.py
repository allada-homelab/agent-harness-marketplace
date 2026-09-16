#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Cluster judged sessions by shared error signature, to surface systemic problems.

After a batch of subagents returns one-line verdicts, `cluster.py` groups the sessions that
share a failure signature (a rootless docker socket path, a `devcontainer.json` lifecycle
command, "permission denied", "not found", …) so a recurring theme is reported as one group
with its session ids instead of being buried across many verdict lines.

Input is read from `--input` (default stdin) and may be:

- the verdict format used by the transcript audit (`<id>|VERDICT=…|SEVERITY=…|<summary>`), or
- a TSV of `<id><TAB><summary>`, or
- a TSV of `<id><TAB><title><TAB><summary>`.

    cat verdicts_*.txt | uv run --script ./cluster.py --min 2
    uv run --script ./cluster.py --input /tmp/verdicts.tsv --min 2 --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict

# (label, regex) — matched case-insensitively against a session's summary.
SIGNATURES: list[tuple[str, re.Pattern]] = [
    ("rootless docker socket / permission denied", re.compile(
        r"/run/user/\d+/docker\.sock|/var/run/docker\.sock|unix://\S+\.sock|"
        r"docker (?:socket|daemon|api).*(?:denied|unreachable|not accessible)|"
        r"permission denied|refused access|denied for everyone", re.I)),
    ("docker hostname / daemon unreachable", re.compile(
        r"could not resolve host:\s*\S+|deepseek-dind|doesn't resolve|does not resolve|"
        r"daemon is unreachable|docker (?:socket|daemon) unreachable", re.I)),
    ("devcontainer.json lifecycle command failed", re.compile(
        r"onCreateCommand|postCreateCommand|post-create\.sh|devcontainer\.json|"
        r"creating the container|An error occurred setting up the container", re.I)),
    ("dev container not found / config missing", re.compile(
        r"Dev container not found|config not found|no such file|not found", re.I)),
    ("devcontainer CLI / exec failed", re.compile(
        r"devcontainer (?:exec|up|status).*(?:failed|error|stack trace)|"
        r"Unknown argument|@devcontainers/cli", re.I)),
    ("exit code failure", re.compile(r"exit code[:\s]*\d+|exit \d+|failed with exit code", re.I)),
    ("uid / userns mapping (root-owned files)", re.compile(
        r"uid \d+|userns|user-namespace|uid-mapping|root-owned|chown|ownership", re.I)),
    ("timeout / hang", re.compile(r"SIGTERM|timed out|timeout|stalled|hung", re.I)),
    ("stack trace / crash", re.compile(r"stack trace|traceback|shell drop", re.I)),
]


def parse_lines(text: str) -> list[tuple[int, str]]:
    """Return (session_id, summary) pairs from verdict or TSV input."""
    out: list[tuple[int, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)\|", line)
        if m and "VERDICT=" in line:
            # <id>|VERDICT=..|SEVERITY=..|<summary>
            sid = int(m.group(1))
            summary = line.split("|", 3)[-1]
            out.append((sid, summary))
            continue
        parts = line.split("\t")
        if parts[0].isdigit():
            sid = int(parts[0])
            summary = parts[-1]
            out.append((sid, summary))
            continue
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", help="file to read (default stdin)")
    ap.add_argument("--min", type=int, default=1, help="minimum sessions per cluster (default 1)")
    ap.add_argument("--json", action="store_true", help="emit the clusters as JSON")
    args = ap.parse_args(argv)

    if args.input:
        text = open(args.input).read()
    else:
        text = sys.stdin.read()
    rows = parse_lines(text)
    if not rows:
        print("cluster: no parseable verdict/summary lines", file=sys.stderr)
        return 1

    clusters: dict[str, list[int]] = defaultdict(list)
    matched_sids: set[int] = set()
    for sid, summary in rows:
        for label, rx in SIGNATURES:
            if rx.search(summary):
                clusters[label].append(sid)
                matched_sids.add(sid)

    # Report every session once, with its matched signatures, so nothing is hidden even
    # if a session matches none of the known signatures.
    unmatched = [sid for sid, _ in rows if sid not in matched_sids]

    ordered = sorted(clusters.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    if args.json:
        print(json.dumps({
            "session_count": len(rows),
            "clusters": [{"label": label, "count": len(sids), "sessions": sorted(sids)}
                         for label, sids in ordered],
            "unmatched_sessions": sorted(unmatched),
        }, indent=2))
        return 0

    print(f"cluster: sessions={len(rows)}")
    shown = 0
    for label, sids in ordered:
        if len(sids) < args.min:
            continue
        shown += 1
        ids = ", ".join(str(x) for x in sorted(sids))
        print(f"  {len(sids):3d}  {label}: {ids}")
    if unmatched:
        print(f"  unmatched (no known signature): {', '.join(str(x) for x in sorted(unmatched))}")
    print(f"cluster: groups shown={shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

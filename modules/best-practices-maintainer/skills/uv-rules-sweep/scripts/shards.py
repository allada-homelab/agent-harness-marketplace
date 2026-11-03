#!/usr/bin/env python3
"""Split a uv source checkout into extraction shards for the uv-rules-sweep workflow.

Usage: python3 -I shards.py <uv-checkout>  ->  JSON list of {id, files: [{path, lines}]}

Pages are taken in path order so a directory stays together, then packed into
shards of about TARGET_LINES. uv.schema.json is its own shard: the settings
reference pages are generated at docs-build time and are not in the checkout,
so the schema is the in-repo source for every [tool.uv] setting.
"""
import json
import sys
from pathlib import Path

TARGET_LINES = 1800  # one reader can hold a shard this size and still quote line numbers
EXCLUDED = "docs/pip/"  # the pip-compatible interface, not project workflow


def lines(path: Path) -> int:
    with path.open(encoding="utf-8") as f:
        return sum(1 for _ in f)


root = Path(sys.argv[1])
pages = sorted(
    rel for rel in (p.relative_to(root).as_posix() for p in (root / "docs").rglob("*.md"))
    if not rel.startswith(EXCLUDED)
)
if not pages or not (root / "uv.schema.json").is_file():
    sys.exit(f"shards.py: {root} is not a uv checkout (no docs/*.md or uv.schema.json)")

shards, current, size = [], [], 0
for page in pages:
    n = lines(root / page)
    if current and size + n > TARGET_LINES:
        shards.append(current)
        current, size = [], 0
    current.append({"path": page, "lines": n})
    size += n
shards.append(current)

out = [{"id": f"docs-{i:02d}", "files": files} for i, files in enumerate(shards, 1)]
out.append({"id": "settings-schema",
            "files": [{"path": "uv.schema.json", "lines": lines(root / "uv.schema.json")}]})
json.dump(out, sys.stdout, indent=1)
print()

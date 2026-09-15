#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Render every module's root `plugin.json` — the Agent Plugins v1.0.0 manifest.

agent-plugins.org (TSC: Amazon, Cursor, Microsoft, OpenAI, Vercel; adopted by
VS Code, Cursor, Copilot, Codex and Kiro) defines a plugin as a directory with
`plugin.json` at its root plus optional `skills/` and `mcp.json`. Our modules
already have `skills/` in that shape, so one manifest per module makes each
installable in those clients too. Claude keeps reading `.claude-plugin/plugin.json`
and pi/dsh keep reading `package.json`; this file is a fourth thin manifest
beside them, and like `modules/index.yaml` it is GENERATED — never hand-edit it.

Source of truth is the module's `package.json` (name, version, description,
license) plus the root `package.json` (`repository`). The schema is closed
(`additionalProperties: false`), so only the permitted fields are written:
$schema, name, version, description, author, homepage, repository, license,
keywords. `agents/`, `hooks/`, `.claude-plugin/`, `package.json` and
`cordis.patch.yml` are simply other files in the plugin root; the spec
neither forbids nor interprets them.

    uv run --script bin/render-plugin-manifests.py --write   # (re)generate
    uv run --script bin/render-plugin-manifests.py --check   # CI: stale or invalid ⇒ exit 1
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "modules"
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
# agent-plugins.org/schemas/1.0.0/plugin.schema.json, `name`.
NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
ALLOWED = {"$schema", "name", "version", "description", "author", "homepage",
           "repository", "license", "keywords", "extensions"}
AUTHOR_ALLOWED = {"name", "email", "url"}
AUTHOR = {"name": "David Allada", "email": "davidanilallada@gmail.com"}


def repo_url() -> str:
    raw = json.loads((ROOT / "package.json").read_text())["repository"]
    if isinstance(raw, dict):
        raw = raw["url"]
    if raw.startswith("github:"):
        return f"https://github.com/{raw[len('github:'):]}"
    return re.sub(r"\.git$", "", raw.replace("git+", ""))


def render(module: Path) -> dict:
    pkg = json.loads((module / "package.json").read_text())
    repo = repo_url()
    doc = {
        "$schema": SCHEMA,
        "name": module.name,
        "version": pkg["version"],
        "description": pkg["description"],
        "author": AUTHOR,
        "homepage": f"{repo}/tree/main/modules/{module.name}",
        "repository": repo,
        "license": pkg.get("license", "MIT"),
        "keywords": ["agent-skills", "claude-code", "pi", "dsh"],
    }
    return doc


def problems(doc: dict, module: Path) -> list[str]:
    out = []
    if doc.get("$schema") != SCHEMA:
        out.append(f"$schema must be {SCHEMA}")
    if not isinstance(doc.get("name"), str) or not NAME_RE.match(doc["name"]) or len(doc["name"]) > 64:
        out.append(f"name {doc.get('name')!r} violates the spec pattern")
    if doc.get("name") != module.name:
        out.append(f"name {doc.get('name')!r} != directory {module.name!r}")
    extra = set(doc) - ALLOWED
    if extra:
        out.append(f"fields outside the closed schema: {sorted(extra)}")
    author = doc.get("author")
    if author is not None and (not isinstance(author, dict) or set(author) - AUTHOR_ALLOWED):
        out.append("author may only carry name/email/url")
    if "keywords" in doc and not all(isinstance(k, str) for k in doc["keywords"]):
        out.append("keywords must be strings")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = ap.parse_args()

    bad = 0
    for module in sorted(p for p in MODULES.iterdir() if p.is_dir() and (p / "package.json").exists()):
        want = render(module)
        target = module / "plugin.json"
        text = json.dumps(want, indent=2) + "\n"
        for problem in problems(want, module):
            print(f"  FAIL {target}: {problem}")
            bad += 1
        if args.write:
            if not target.exists() or target.read_text() != text:
                target.write_text(text)
                print(f"  wrote {target.relative_to(ROOT)}")
        else:
            if not target.exists():
                print(f"  FAIL {target.relative_to(ROOT)} missing — run bin/render-plugin-manifests.py --write")
                bad += 1
            elif target.read_text() != text:
                print(f"  FAIL {target.relative_to(ROOT)} is stale — run bin/render-plugin-manifests.py --write")
                bad += 1
    if args.check and not bad:
        print("  ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

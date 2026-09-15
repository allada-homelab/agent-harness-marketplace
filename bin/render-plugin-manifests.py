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

The same spec defines an optional `mcp.json` at the plugin root. A module that
ships one declares its MCP servers once: Claude Code reads the *other* spelling,
`.mcp.json` (`mcpServers` only, no `$schema`), so that file is GENERATED from
`mcp.json` here, and pi and dsh consume `mcp.json` through the harness layer's
MCP registry. `--check-mcp` validates the source and the generated copy.

    uv run --script bin/render-plugin-manifests.py --write      # (re)generate both
    uv run --script bin/render-plugin-manifests.py --check      # CI: stale or invalid plugin.json ⇒ exit 1
    uv run --script bin/render-plugin-manifests.py --check-mcp  # CI: stale or invalid mcp.json ⇒ exit 1
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "modules"
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
# agent-plugins.org/schemas/1.0.0/plugin.schema.json, `name`.
NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
ALLOWED = {"$schema", "name", "version", "description", "author", "homepage",
           "repository", "license", "keywords", "extensions"}
AUTHOR_ALLOWED = {"name", "email", "url"}
AUTHOR = {"name": "David Allada", "email": "davidanilallada@gmail.com"}

MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
MCP_TOP = {"$schema", "mcpServers"}
SERVER_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
SERVER_KEYS = {"stdio": {"type", "command", "args", "env"},
               "streamable-http": {"type", "url", "headers"},
               "sse": {"type", "url", "headers"}}
# `command` is exec'd directly, never through a shell: one executable token.
SHELL_META = set(" \t\n;|&<>$`()*?~\"'\\")
LOOPBACK = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]", ""}
# A credential must be an indirection the installing machine resolves, never a literal.
SECRETISH = re.compile(r"(key|token|secret|password|passwd|authorization|credential)", re.I)
REF = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")
TOKENISH = re.compile(r"[A-Za-z0-9._-]{16,}")  # what is left once the references are removed


def mcp_problems(doc: object) -> list[str]:
    """Every way a module's mcp.json can be wrong. Empty list ⇒ valid."""
    out: list[str] = []
    if not isinstance(doc, dict):
        return ["mcp.json must be a JSON object"]
    if extra := set(doc) - MCP_TOP:
        out.append(f"fields outside the closed top-level shape: {sorted(extra)}")
    if "$schema" in doc and doc["$schema"] != MCP_SCHEMA:
        out.append(f"$schema must be {MCP_SCHEMA}")
    servers = doc.get("mcpServers")
    if not isinstance(servers, dict):
        return out + ["mcpServers must be an object of <name> → server"]
    for name, srv in servers.items():
        where = f"mcpServers.{name}"
        if not SERVER_NAME_RE.fullmatch(name):
            out.append(f"{where}: name must match [A-Za-z0-9_-]{{1,32}}")
        if not isinstance(srv, dict):
            out.append(f"{where}: must be an object"); continue
        kind = srv.get("type")
        if kind not in SERVER_KEYS:
            out.append(f"{where}: type must be one of {sorted(SERVER_KEYS)}, got {kind!r}"); continue
        if extra := set(srv) - SERVER_KEYS[kind]:
            out.append(f"{where}: fields outside the {kind} shape: {sorted(extra)}")
        if kind == "stdio":
            command = srv.get("command")
            if not isinstance(command, str) or not command:
                out.append(f"{where}: command is required")
            elif set(command) & SHELL_META:
                out.append(f"{where}: command {command!r} must be a single executable token — "
                           "no shell string; put the rest in args")
            args = srv.get("args", [])
            if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                out.append(f"{where}: args must be a list of strings")
        else:
            url = srv.get("url")
            if not isinstance(url, str):
                out.append(f"{where}: url is required")
            else:
                parts = urlsplit(url)
                if parts.scheme != "https":
                    out.append(f"{where}: url must be https, got {url!r}")
                if parts.hostname in LOOPBACK or parts.hostname is None:
                    out.append(f"{where}: url {url!r} points at loopback; a module ships no host-local server")
        for field in ("env", "headers"):
            values = srv.get(field)
            if values is None:
                continue
            if not isinstance(values, dict) or not all(isinstance(v, str) for v in values.values()):
                out.append(f"{where}: {field} must be an object of string values"); continue
            for key, value in values.items():
                if not SECRETISH.search(key):
                    continue
                if not REF.search(value) or TOKENISH.search(REF.sub("", value)):
                    out.append(f"{where}: {field}.{key} names a credential but its value carries a "
                               "literal — use a ${VAR} reference the installing machine resolves")
    return out


def render_mcp(doc: dict) -> dict:
    """Claude Code's spelling of the same servers: `.mcp.json`, no $schema."""
    return {"mcpServers": doc["mcpServers"]}


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
    mode.add_argument("--check-mcp", action="store_true", dest="check_mcp")
    args = ap.parse_args()

    if args.check_mcp:
        return check_mcp()

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
            bad += write_mcp(module)
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


def write_mcp(module: Path) -> int:
    source, target = module / "mcp.json", module / ".mcp.json"
    if not source.exists():
        if target.exists():
            print(f"  FAIL {target.relative_to(ROOT)} has no source mcp.json — it is generated, not hand-written")
            return 1
        return 0
    doc = json.loads(source.read_text())
    if problems := mcp_problems(doc):
        for problem in problems:
            print(f"  FAIL {source.relative_to(ROOT)}: {problem}")
        return len(problems)
    text = json.dumps(render_mcp(doc), indent=2) + "\n"
    if not target.exists() or target.read_text() != text:
        target.write_text(text)
        print(f"  wrote {target.relative_to(ROOT)}")
    return 0


def check_mcp() -> int:
    bad = 0
    for module in sorted(p for p in MODULES.iterdir() if p.is_dir()):
        source, target = module / "mcp.json", module / ".mcp.json"
        if not source.exists():
            if target.exists():
                print(f"  FAIL {target.relative_to(ROOT)} has no source mcp.json — it is generated, not hand-written")
                bad += 1
            continue
        try:
            doc = json.loads(source.read_text())
        except json.JSONDecodeError as e:
            print(f"  FAIL {source.relative_to(ROOT)}: not valid JSON ({e})"); bad += 1; continue
        if problems := mcp_problems(doc):
            for problem in problems:
                print(f"  FAIL {source.relative_to(ROOT)}: {problem}")
            bad += len(problems)
            continue
        text = json.dumps(render_mcp(doc), indent=2) + "\n"
        if not target.exists() or target.read_text() != text:
            print(f"  FAIL {target.relative_to(ROOT)} is stale or missing — run bin/render-plugin-manifests.py --write")
            bad += 1
    print("  ok" if not bad else f"  {bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

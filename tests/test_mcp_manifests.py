"""bin/render-plugin-manifests.py: the portable `mcp.json` and the `.mcp.json` Claude reads.

One source file per module (Agent Plugins v1 shape); the Claude spelling beside it
is generated from it. See docs/authoring.md, "MCP servers".
"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mcp"

_spec = importlib.util.spec_from_file_location("render_plugin_manifests",
                                               ROOT / "bin" / "render-plugin-manifests.py")
rpm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rpm)

VALID = json.loads((FIXTURES / "mcp.json").read_text())


def test_fixture_is_valid():
    assert rpm.mcp_problems(VALID) == []


def test_rendered_claude_form_matches_the_fixture():
    text = json.dumps(rpm.render_mcp(VALID), indent=2) + "\n"
    assert text == (FIXTURES / ".mcp.json").read_text()
    assert "$schema" not in json.loads(text)


def mutate(**servers):
    doc = copy.deepcopy(VALID)
    doc["mcpServers"].update(servers)
    return doc


CASES = {
    "unknown top-level field": {**VALID, "hooks": {}},
    "mcpServers missing": {"$schema": rpm.MCP_SCHEMA},
    "wrong $schema": {**VALID, "$schema": "https://example.com/other.json"},
    "server name too long": mutate(**{"x" * 33: VALID["mcpServers"]["docs"]}),
    "server name with a dot": mutate(**{"docs.v2": VALID["mcpServers"]["docs"]}),
    "unknown transport": mutate(docs={"type": "websocket", "url": "https://mcp.example.com"}),
    "stdio without command": mutate(docs={"type": "stdio", "args": ["x"]}),
    "stdio command is a shell string": mutate(docs={"type": "stdio", "command": "npx -y pkg"}),
    "stdio args not strings": mutate(docs={"type": "stdio", "command": "npx", "args": [1]}),
    "stdio field outside the shape": mutate(docs={"type": "stdio", "command": "npx", "url": "https://x.example.com"}),
    "remote url is not https": mutate(search={"type": "sse", "url": "http://mcp.example.com/s"}),
    "remote url is loopback": mutate(search={"type": "sse", "url": "https://localhost:7000/s"}),
    "literal credential in env": mutate(docs={"type": "stdio", "command": "npx",
                                              "env": {"DOCS_API_KEY": "sk-live-0123456789abcdef"}}),
    "literal credential in a header": mutate(search={"type": "streamable-http", "url": "https://mcp.example.com/s",
                                                     "headers": {"X-Api-Token": "abcdef0123456789abcdef"}}),
    "credential with a reference plus a literal": mutate(
        search={"type": "streamable-http", "url": "https://mcp.example.com/s",
                "headers": {"Authorization": "Bearer ${T} 0123456789abcdef0123"}}),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_invalid_manifests_are_rejected(name):
    assert rpm.mcp_problems(CASES[name]), f"{name} was accepted"


def test_non_credential_literals_are_left_alone():
    doc = mutate(docs={"type": "stdio", "command": "npx", "env": {"DOCS_MODE": "offline"}})
    assert rpm.mcp_problems(doc) == []


def test_no_module_ships_an_unsourced_claude_file():
    orphans = [p for p in (ROOT / "modules").glob("*/.mcp.json") if not (p.parent / "mcp.json").exists()]
    assert orphans == []

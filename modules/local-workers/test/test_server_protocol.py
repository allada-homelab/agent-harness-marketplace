"""Drive the real server over stdio with the MCP SDK client, against the fake shim."""

import asyncio
import json
import os
from pathlib import Path

import pytest
from fake_shim import FakeShim
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

PLUGIN = Path(__file__).resolve().parent.parent
SERVER = PLUGIN / "server" / "server.py"


@pytest.fixture
def shim():
    with FakeShim() as s:
        yield s


def call(shim_url: str, fn):
    env = {**os.environ, "LW_DECISION_URL": shim_url}
    params = StdioServerParameters(command="uv", args=["run", "--quiet", "--script", str(SERVER)], env=env)

    async def go():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            init = await session.initialize()
            return await fn(session, init)

    return asyncio.run(go())


def test_lists_decide_with_contract(shim):
    async def fn(session, init):
        return init, (await session.list_tools()).tools

    init, tools = call(shim.url, fn)
    by_name = {t.name: t for t in tools}
    assert set(by_name) == {"decide"}
    assert len(init.instructions) <= 700
    for tool in tools:
        assert tool.annotations.read_only_hint is True
        assert len(tool.description.splitlines()) >= 3
        assert len(tool.description) <= 600
    assert by_name["decide"].input_schema["required"] == ["items"]


def test_decide_round_trip(shim):
    items = [{"id": "t1", "state": "ticket", "questions": {"bug": {"type": "noul", "instructions": "Bug?"}}}]

    async def fn(session, _):
        return await session.call_tool("decide", {"items": items})

    body = json.loads(call(shim.url, fn).content[0].text)
    assert body["summary"]["ok"] == 1 and body["results"][0]["answers"]["bug"]["noul"] == 0.95


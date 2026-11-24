# /// script
# requires-python = ">=3.13"
# dependencies = ["mcp>=2.1,<3", "pydantic>=2"]
# ///
"""local-workers MCP server: hand explicitly requested work to self-hosted models.

One tool, `decide`: a batch of typed decisions for the d3-ultra decision model. It never falls back to
an Anthropic model; failures come back as results. The pi agent is the plugin's `bin/pi-run` script.
"""

import asyncio
import json
import os
import sys
from typing import Annotated, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decision_client import decide_batch, fetch_health  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp_types import ToolAnnotations  # noqa: E402
from pydantic import Field  # noqa: E402


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    # An unset userConfig can arrive as the literal placeholder; treat it as unset.
    return default if not value or value.startswith("${") else value


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(float(_env(name, str(default)))))
    except ValueError:
        return default


DECISION_URL = _env("LW_DECISION_URL", "http://10.69.1.169:8690/upstream/decision-default").rstrip("/")
DECIDE_CONCURRENCY = _env_int("LW_DECIDE_CONCURRENCY", 8)
_health: dict | None = None

mcp = MCPServer(
    "local",
    title="local-workers",
    description="Self-hosted worker: the d3-ultra decision model.",
    instructions=(
        "Use only when the user explicitly asks for the local decision model. decide answers typed "
        "questions in batches; treat floored, low_confidence or possibly_truncated answers as no decision. "
        "Nothing here falls back to a paid model."
    ),
)


@mcp.tool(
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                                open_world_hint=False),
    structured_output=False,
)
async def decide(
    items: Annotated[list[dict[str, Any]], Field(description=(
        "Records to decide on, 1+ items, at most 128 questions in total. Each item: "
        "{id?: str, state: str | object, images?: [data URI | base64 | URL], questions: {qid: question}}. "
        "question = {type: 'choice'|'noul'|'score', instructions: str, criteria: ..., threshold?: 0..1}; "
        "choice criteria = {option: description}; noul criteria = {true: desc, false: desc}; "
        "score criteria = [level descriptions, low to high]."))],
) -> str:
    """Answer typed decision questions about records with the local d3-ultra decision model.

    Batch only: put every record in one call and group a record's questions in one item. Types: choice
    (pick one option), noul (probability a statement is true), score (level on an ordered scale). A
    record plus question over ~22.5k tokens comes back invalid. Returns JSON results per item with floored,
    low_confidence and possibly_truncated flags; treat flagged answers as no decision.
    """
    global _health
    health = _health or await asyncio.to_thread(fetch_health, DECISION_URL)
    if not health.get("fallback"):
        _health = health  # cache only the shim's real values, never the cold-start fallback
    result = await asyncio.to_thread(decide_batch, DECISION_URL, items, DECIDE_CONCURRENCY, 30, health)
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    mcp.run("stdio")

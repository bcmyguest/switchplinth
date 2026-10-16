"""Stdio MCP server identity under the switchplinth package name, offline."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

FIXTURE_BOOTSTRAP = Path(__file__).resolve().parents[2] / "fixtures" / "food-delivery" / "bootstrap.py"
# An unroutable Qdrant URL: any accidental Qdrant call fails instead of reaching a service.
OFFLINE_ENV = {"QDRANT_URL": "http://127.0.0.1:9", "NO_PROXY": "*"}


def _bootstrap(root: Path) -> None:
    spec = importlib.util.spec_from_file_location("food_delivery_bootstrap_name", FIXTURE_BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.bootstrap(root)


async def _initialize(repo: Path, cache: Path) -> tuple[str, set[str]]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "switchplinth.cli", "mcp", "--repo", str(repo), "--cache", str(cache)],
        env={**os.environ, **OFFLINE_ENV},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            tools = (await session.list_tools()).tools
            return initialized.serverInfo.name, {tool.name for tool in tools}


def test_stdio_server_reports_switchplinth_name(tmp_path: Path) -> None:
    import switchplinth
    from switchplinth.api import create_app
    from switchplinth.local_vectors import LocalVectorIndex
    from switchplinth.service import DecisionService

    assert switchplinth.MCP_SERVER_NAME == "io.github.bcmyguest/switchplinth"
    repo = tmp_path / "food-delivery"
    _bootstrap(repo)
    name, tools = asyncio.run(asyncio.wait_for(_initialize(repo, tmp_path / "mcp-cache"), timeout=60))
    assert name == switchplinth.MCP_SERVER_NAME
    assert {"list_decisions", "search_decisions", "inspect_architecture", "inspect_entity"} <= tools

    app = create_app(DecisionService(repo, tmp_path / "http-cache", LocalVectorIndex()))
    assert app.state.mcp_server.name == switchplinth.MCP_SERVER_NAME
    assert {tool.name for tool in asyncio.run(app.state.mcp_server.list_tools())} == tools

"""Stdio MCP initialize reports switchplinth's own name and package version, offline."""

from __future__ import annotations

import asyncio
import importlib.metadata
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
    spec = importlib.util.spec_from_file_location("food_delivery_bootstrap_version", FIXTURE_BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.bootstrap(root)


async def _server_info(repo: Path, cache: Path) -> tuple[str, str]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "switchplinth.cli", "mcp", "--repo", str(repo), "--cache", str(cache)],
        env={**os.environ, **OFFLINE_ENV},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            info = (await session.initialize()).serverInfo
            return info.name, info.version


def test_stdio_initialize_reports_switchplinth_version(tmp_path: Path) -> None:
    import switchplinth

    expected = importlib.metadata.version("switchplinth")
    assert switchplinth.__version__ == expected
    assert expected != importlib.metadata.version("mcp")
    repo = tmp_path / "food-delivery"
    _bootstrap(repo)
    name, version = asyncio.run(asyncio.wait_for(_server_info(repo, tmp_path / "mcp-cache"), timeout=60))
    assert name == switchplinth.MCP_SERVER_NAME
    assert version == expected

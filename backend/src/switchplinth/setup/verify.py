"""Verify an MCP server the way a client does: initialize, then tools/list."""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from typing import Mapping

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

VERIFY_TIMEOUT_SECONDS = 90


@dataclass(frozen=True)
class VerifyResult:
    server_name: str
    tools: tuple[str, ...]


async def _session_check(read, write) -> VerifyResult:
    async with ClientSession(read, write) as session:
        initialized = await session.initialize()
        tools = (await session.list_tools()).tools
        return VerifyResult(initialized.serverInfo.name, tuple(sorted(tool.name for tool in tools)))


async def _stdio(command: list[str], env: Mapping[str, str]) -> VerifyResult:
    params = StdioServerParameters(command=command[0], args=command[1:], env=dict(env))
    # Keep the server's request log off the wizard's output; show it only on failure.
    with tempfile.TemporaryFile("w+", encoding="utf-8") as errlog:
        try:
            async with stdio_client(params, errlog=errlog) as (read, write):
                return await _session_check(read, write)
        except BaseException as exc:
            errlog.seek(0)
            tail = "\n".join(errlog.read().strip().splitlines()[-10:])
            if tail and isinstance(exc, Exception):
                raise RuntimeError(f"{type(exc).__name__}: {exc}; server stderr:\n{tail}") from exc
            raise


async def _http(url: str) -> VerifyResult:
    async with streamablehttp_client(url) as (read, write, _session_id):
        return await _session_check(read, write)


def verify_stdio(command: list[str], env: Mapping[str, str] | None = None, timeout: float = VERIFY_TIMEOUT_SECONDS) -> VerifyResult:
    """Start the configured stdio command and return its server name and tools."""
    return asyncio.run(asyncio.wait_for(_stdio(command, env if env is not None else os.environ), timeout))


def verify_http(url: str, timeout: float = VERIFY_TIMEOUT_SECONDS) -> VerifyResult:
    return asyncio.run(asyncio.wait_for(_http(url), timeout))

"""Command-line entry point: the HTTP API (default) or a stdio MCP server.

The console-script name lives only in pyproject.toml `[project.scripts]`.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from switchplinth import DEFAULT_CACHE_ROOT, PRODUCT_NAME


def _cache_for(root: Path, cache: Path | None) -> Path:
    if cache is not None:
        return cache
    namespace = hashlib.sha256(root.as_posix().encode()).hexdigest()[:16]
    return Path(os.environ.get("DECISION_CACHE", DEFAULT_CACHE_ROOT)) / namespace


def open_stdio_service(repo: Path, cache: Path | None = None, scan: bool = False):
    """Open a repository for stdio MCP use without a Qdrant service.

    A repository connection with embeddings enabled is still called for index
    rebuild and each search; when it is unreachable, vector search reports an
    error and lexical search still answers.
    """
    from switchplinth.local_vectors import LocalVectorIndex
    from switchplinth.service import DecisionService

    root = repo.resolve()
    if not root.is_dir():
        raise SystemExit(f"Repository directory not found: {root}")
    service = DecisionService(root, _cache_for(root, cache), LocalVectorIndex())
    if scan:
        service.scan()
    else:
        service.rebuild_indexes()
    return service


def serve_mcp_stdio(repo: Path, cache: Path | None = None, scan: bool = False) -> None:
    from switchplinth.mcp_tools import create_mcp_server

    service = open_stdio_service(repo, cache, scan)
    create_mcp_server(lambda: service).run("stdio")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"{PRODUCT_NAME} backend. Without a command, serve the HTTP API on port 8000.")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="serve the HTTP API and /mcp endpoint (default)")
    mcp = commands.add_parser("mcp", help="serve the read-only MCP tools over stdio; no Docker, Qdrant, or model needed")
    mcp.add_argument("--repo", type=Path, default=Path("."), help="repository directory with Markdown and .decision/ (default: current directory)")
    mcp.add_argument("--cache", type=Path, help=f"disposable SQLite cache directory (default: $DECISION_CACHE or {DEFAULT_CACHE_ROOT}, namespaced by repository)")
    mcp.add_argument("--scan", action="store_true", help="run deterministic mock extraction first; writes inferred records under .decision/")
    args = parser.parse_args(argv)
    if args.command == "mcp":
        serve_mcp_stdio(args.repo, args.cache, args.scan)
        return
    from switchplinth.api import run

    run()


if __name__ == "__main__":
    main(sys.argv[1:])

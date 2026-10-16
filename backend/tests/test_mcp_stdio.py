"""Stdio MCP entry point against a bootstrapped food-delivery fixture, offline."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

FIXTURE_BOOTSTRAP = Path(__file__).resolve().parents[2] / "fixtures" / "food-delivery" / "bootstrap.py"
EXPECTED_TOOLS = {"list_decisions", "search_decisions", "inspect_architecture", "inspect_entity"}
# An unroutable Qdrant URL: any accidental Qdrant call fails instead of reaching a service.
OFFLINE_ENV = {"QDRANT_URL": "http://127.0.0.1:9", "NO_PROXY": "*"}


def _bootstrap(root: Path) -> None:
    spec = importlib.util.spec_from_file_location("food_delivery_bootstrap", FIXTURE_BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.bootstrap(root)


def _payload(result) -> dict:
    assert not result.isError, result.content
    return result.structuredContent.get("result", result.structuredContent) if result.structuredContent else json.loads(result.content[0].text)


async def _exercise(repo: Path, cache: Path) -> dict:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "switchplinth.cli", "mcp", "--repo", str(repo), "--cache", str(cache)],
        env={**os.environ, **OFFLINE_ENV},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            decisions = _payload(await session.call_tool("list_decisions", {}))
            sqs = next(d for d in decisions["decisions"] if any("SQS" in o["title"] for o in d["options"]))
            sqs_option = next(o for o in sqs["options"] if "SQS" in o["title"])
            search = _payload(await session.call_tool("search_decisions", {"query": "Why are we using Kafka?"}))
            selections = {sqs["id"]: sqs_option["id"]}
            scenario = _payload(await session.call_tool("list_decisions", {"selections": selections}))
            architecture = _payload(await session.call_tool("inspect_architecture", {}))
            preview = _payload(await session.call_tool("inspect_architecture", {"selections": selections}))
            kafka = next(entity for entity in architecture["entities"] if entity["name"].casefold() == "apache kafka")
            entity = _payload(await session.call_tool("inspect_entity", {"entity_id": kafka["id"]}))
            missing = await session.call_tool("inspect_entity", {"entity_id": "no-such-entity"})
            return {"tools": tools, "decisions": decisions, "sqs": (sqs["id"], sqs_option["id"]), "search": search, "scenario": scenario, "architecture": architecture, "preview": preview, "kafka": kafka["id"], "entity": entity, "missing": missing}


@pytest.fixture
def food_delivery(tmp_path: Path) -> Path:
    repo = tmp_path / "food-delivery"
    _bootstrap(repo)
    return repo


def test_stdio_server_lists_and_answers_tools(food_delivery: Path, tmp_path: Path) -> None:
    before = {path: path.read_bytes() for path in (food_delivery / ".decision").rglob("*.yaml")}
    outcome = asyncio.run(asyncio.wait_for(_exercise(food_delivery, tmp_path / "mcp-cache"), timeout=60))

    tools = {tool.name: tool for tool in outcome["tools"]}
    assert EXPECTED_TOOLS <= set(tools)
    for name in EXPECTED_TOOLS:
        assert tools[name].annotations.readOnlyHint is True
        assert len(tools[name].description) > 120
    assert "selections" in tools["search_decisions"].description

    decisions = outcome["decisions"]["decisions"]
    assert len(decisions) == 7
    for decision in decisions:
        assert set(decision) == {"id", "title", "status", "selected_option", "options", "needs_review"}
        assert all(set(option) == {"id", "title"} for option in decision["options"])
    assert any(decision["selected_option"] for decision in decisions)

    decision_id, option_id = outcome["sqs"]
    assert outcome["scenario"]["selections"][decision_id] == option_id

    search = outcome["search"]
    assert search["evidence"], search
    assert any("kafka" in item["text"].casefold() for item in search["evidence"])
    assert search["semantic_index"]["mode"] == "deterministic_local"
    assert search["vector_search"]["status"] == "supported"

    architecture, preview = outcome["architecture"], outcome["preview"]
    assert architecture["entities"] and architecture["relationships"]
    assert preview["scenario"]["selections"][decision_id] == option_id
    assert architecture["scenario"]["selections"][decision_id] != option_id
    assert preview["scenario"]["affected_decisions"]

    entity = outcome["entity"]
    assert entity["entity"]["id"] == outcome["kafka"]
    assert entity["relationships"] and entity["decisions"]

    assert outcome["missing"].isError

    # The HTTP /mcp mount exposes the same tools and descriptions as stdio.
    from switchplinth.api import create_app
    from switchplinth.local_vectors import LocalVectorIndex
    from switchplinth.service import DecisionService

    app = create_app(DecisionService(food_delivery, tmp_path / "http-cache", LocalVectorIndex()))
    http_tools = asyncio.run(app.state.mcp_server.list_tools())
    assert {tool.name: tool.description for tool in http_tools} == {tool.name: tool.description for tool in outcome["tools"]}
    # Read-only: serving and querying left canonical YAML unchanged.
    assert {path: path.read_bytes() for path in (food_delivery / ".decision").rglob("*.yaml")} == before


def test_local_vector_index_ranks_matching_passage() -> None:
    from switchplinth.domain import Evidence, Graph
    from switchplinth.local_vectors import LocalVectorIndex

    index = LocalVectorIndex()
    unbuilt: dict[str, str] = {}
    assert index.search("kafka", None, unbuilt) == []
    assert unbuilt["status"] == "unsupported"
    passages = [Evidence("a", "a.md", ["A"], "x", text="orders publish events to kafka"), Evidence("b", "b.md", ["B"], "y", text="menu cache uses redis")]
    assert index.rebuild(passages, Graph(), None).startswith("indexed 2")
    diagnostics: dict[str, str] = {}
    hits = index.search("kafka events", None, diagnostics)
    assert hits[0]["evidence_id"] == "a"
    assert diagnostics["status"] == "supported"


def test_service_routes_vector_calls_through_injected_index(food_delivery: Path, tmp_path: Path) -> None:
    from switchplinth.service import DecisionService

    class RecordingIndex:
        kind = "recorder"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def rebuild(self, passages, graph, embedder) -> str:
            self.calls.append(f"rebuild:{len(passages)}")
            return "indexed by recorder"

        def search(self, query, embedder, diagnostics):
            self.calls.append(f"search:{query}")
            diagnostics.update(status="supported", detail="recorder")
            return []

    index = RecordingIndex()
    service = DecisionService(food_delivery, tmp_path / "cache", index)
    status = service.rebuild_indexes()
    assert status["qdrant"] == "indexed by recorder"
    assert status["vector_index"] == {"kind": "recorder", "status": "indexed by recorder"}
    service.search("kafka")
    assert index.calls[0].startswith("rebuild:") and index.calls[-1] == "search:kafka"


def test_cli_rejects_missing_repository(tmp_path: Path) -> None:
    from switchplinth.cli import main

    with pytest.raises(SystemExit, match="not found"):
        main(["mcp", "--repo", str(tmp_path / "absent"), "--cache", str(tmp_path / "cache")])

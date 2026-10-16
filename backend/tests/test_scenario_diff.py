"""Scenario diff, input receipts, and downstream impact (pure module, service, REST, and MCP)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from switchplinth.api import create_app
from switchplinth.domain import Decision, Entity, Graph, Option, Relationship, passage_hash
from switchplinth.local_vectors import LocalVectorIndex
from switchplinth.mcp_tools import create_mcp_server
from switchplinth.scenario_analysis import ResolvedScenario, diff_resolved_scenarios, downstream_impact
from switchplinth.service import DecisionService

FIXTURE_BOOTSTRAP = Path(__file__).resolve().parents[2] / "fixtures" / "food-delivery" / "bootstrap.py"
EVENT_TRANSPORT = "decision-9069314c598bbe6a"
KAFKA_OPTION = "option-0e42fd4e38cd9281"
SQS_OPTION = "option-2d494dede037e255"
ORDER_SERVICE = "entity-225ac6a9466f917c"
KAFKA_STREAM = "resource-bc094960cda1ecbb"
SQS_STREAM = "resource-a755d86bd792bfe6"
KAFKA_PUBLISH = "relationship-dcc3e8c1188a2d38"
SQS_PUBLISH = "relationship-27d4255d512327af"
RECEIPT_SCRIPT = (
    "import json, sys; from pathlib import Path; "
    "from switchplinth.service import DecisionService; from switchplinth.local_vectors import LocalVectorIndex; "
    "s = DecisionService(Path(sys.argv[1]), Path(sys.argv[2]), vector_index=LocalVectorIndex()); "
    "print(s.graph_json(json.loads(sys.argv[3]))['receipt']['digest'])"
)


def chain_graph(length: int) -> Graph:
    """e0 -> e1 -> ... -> e{length-1}: each entity depends on the next one."""
    entities = {f"e{index}": Entity(f"e{index}", "service", f"E{index}") for index in range(length)}
    relationships = {f"r{index}": Relationship(f"r{index}", f"e{index}", f"e{index + 1}", "calls") for index in range(length - 1)}
    return Graph(entities, relationships)


def without(graph: Graph, entity_id: str) -> Graph:
    return Graph(
        {key: value for key, value in graph.entities.items() if key != entity_id},
        {key: value for key, value in graph.relationships.items() if entity_id not in (value.source, value.target)},
    )


@pytest.fixture(scope="module")
def food_delivery(tmp_path_factory: pytest.TempPathFactory) -> Path:
    spec = importlib.util.spec_from_file_location("food_delivery_bootstrap", FIXTURE_BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path_factory.mktemp("fd") / "food-delivery"
    module.bootstrap(root)
    return root


@pytest.fixture
def repo(food_delivery: Path, tmp_path: Path) -> Path:
    copy = tmp_path / "food-delivery"
    shutil.copytree(food_delivery, copy)
    return copy


def service_for(root: Path, cache: Path) -> DecisionService:
    return DecisionService(root, cache, vector_index=LocalVectorIndex())


def test_impact_walks_dependents_transitively_with_paths_and_depth_cap() -> None:
    before = chain_graph(7)
    after = without(before, "e6")
    impact = downstream_impact(before, after, max_depth=4)
    assert [(item["type"], item["id"], item["change"]) for item in impact["items"]] == [("entity", "e6", "removed")]
    item = impact["items"][0]
    assert [(dep["entity_id"], dep["depth"]) for dep in item["dependents"]] == [("e5", 1), ("e4", 2), ("e3", 3), ("e2", 4)]
    assert item["dependents"][2]["path"] == ["e3", "r3", "e4", "r4", "e5", "r5", "e6"]
    assert item["truncated"] is True
    assert item["dependents"][0]["points_at_missing"] is True
    assert item["dependents"][0]["missing_endpoints"] == [{"relationship_id": "r5", "kind": "calls", "missing_entity_id": "e6", "status": "dangling", "rewired_to": []}]
    assert item["dependents"][0]["rewired"] is False
    assert item["dependents"][1]["points_at_missing"] is False
    assert "No code analysis" in impact["limits"]
    full = downstream_impact(before, after, max_depth=10)["items"][0]
    assert full["truncated"] is False and len(full["dependents"]) == 6


def test_missing_endpoints_count_only_outgoing_edges_and_detect_rewiring() -> None:
    before = chain_graph(3)
    after = without(without(before, "e0"), "e2")
    [removed_e0, removed_e2] = downstream_impact(before, after)["items"]
    assert removed_e0["dependents"] == []
    assert [dep["entity_id"] for dep in removed_e2["dependents"]] == ["e1", "e0"]
    e1 = removed_e2["dependents"][0]
    # e0 -> e1 also lost its source, but only e1's own outgoing edge r1 points at a missing entity.
    assert [item["relationship_id"] for item in e1["missing_endpoints"]] == ["r1"]
    assert e1["points_at_missing"] is True and e1["rewired"] is False

    rewired_after = Graph({**after.entities, "n2": Entity("n2", "service", "N2")}, {"r-new": Relationship("r-new", "e1", "n2", "calls"), "r-other": Relationship("r-other", "e1", "n2", "uses")})
    [_, rewired_e2] = downstream_impact(before, rewired_after)["items"]
    e1 = rewired_e2["dependents"][0]
    assert e1["missing_endpoints"] == [{"relationship_id": "r1", "kind": "calls", "missing_entity_id": "e2", "status": "rewired", "rewired_to": [{"relationship_id": "r-new", "to": "n2"}]}]
    assert e1["points_at_missing"] is False and e1["rewired"] is True


def test_impact_order_is_deterministic_and_handles_cycles_and_replaced_relationships() -> None:
    entities = {name: Entity(name, "service", name.upper()) for name in ("a", "b", "c", "x")}
    relationships = {
        "r-ab": Relationship("r-ab", "a", "b", "calls"),
        "r-bc": Relationship("r-bc", "b", "c", "calls"),
        "r-ca": Relationship("r-ca", "c", "a", "calls"),
        "r-xb": Relationship("r-xb", "x", "b", "uses"),
    }
    before = Graph(entities, relationships)
    after = Graph(dict(entities), {**relationships, "r-bc": Relationship("r-bc", "b", "x", "calls")})
    impact = downstream_impact(before, after)
    assert [(item["type"], item["id"], item["change"]) for item in impact["items"]] == [("relationship", "r-bc", "replaced")]
    dependents = impact["items"][0]["dependents"]
    assert [(dep["entity_id"], dep["depth"]) for dep in dependents] == [("b", 1), ("a", 2), ("x", 2)]
    assert dependents[0]["path"] == ["b", "r-bc", "c"]
    reversed_before = Graph(dict(reversed(list(entities.items()))), dict(reversed(list(relationships.items()))))
    assert downstream_impact(reversed_before, after) == impact


def test_diff_reports_records_problems_and_affected_decisions_between_arbitrary_scenarios() -> None:
    base = chain_graph(3)
    option_a = Option("opt-a", "A", "", {"operations": [{"op": "remove_entity", "entity": {"id": "e2"}}]})
    option_b = Option("opt-b", "B", "", {"operations": [{"op": "add_entity", "entity": {"id": "n1", "kind": "service", "name": "N1"}}]})
    decisions = [Decision("d1", "Choose", "decided", "", "opt-a", [option_a, option_b]), Decision("d2", "Other", "decided", "", None, [])]
    before = ResolvedScenario({"d1": "opt-a"}, without(base, "e2"), ["old conflict"], ["shared", "gone"])
    after_graph = Graph({**base.entities, "n1": Entity("n1", "service", "N1")}, dict(base.relationships))
    after = ResolvedScenario({"d1": "opt-b"}, after_graph, [], ["shared", "new"])
    diff = diff_resolved_scenarios(before, after, decisions)
    assert diff["selection_changes"] == [{"decision_id": "d1", "before_option": "opt-a", "after_option": "opt-b"}]
    assert [entity["id"] for entity in diff["entities"]["added"]] == ["e2", "n1"]
    assert diff["entities"]["removed"] == [] and diff["entities"]["changed"] == []
    assert [rel["id"] for rel in diff["relationships"]["added"]] == ["r1"]
    assert diff["conflicts"] == {"appeared": [], "disappeared": ["old conflict"]}
    assert diff["invalid_assumptions"] == {"appeared": ["new"], "disappeared": ["gone"]}
    assert diff["affected_decisions"] == [{"id": "d1", "title": "Choose", "reasons": ["selection_changed", "options_reference_changed_elements"]}]
    assert diff["impact"]["items"] == []
    reverse = diff_resolved_scenarios(after, before, decisions)
    assert [entity["id"] for entity in reverse["entities"]["removed"]] == ["e2", "n1"]
    assert [(item["id"], [dep["entity_id"] for dep in item["dependents"]]) for item in reverse["impact"]["items"]] == [("e2", ["e1", "e0"]), ("n1", [])]


def test_food_delivery_event_transport_switch_diff_and_impact(repo: Path, tmp_path: Path) -> None:
    service = service_for(repo, tmp_path / "cache")
    diff = service.diff_scenarios(None, {EVENT_TRANSPORT: SQS_OPTION})
    assert diff["selection_changes"] == [{"decision_id": EVENT_TRANSPORT, "before_option": KAFKA_OPTION, "after_option": SQS_OPTION}]
    assert [entity["id"] for entity in diff["entities"]["removed"]] == [KAFKA_STREAM]
    assert [entity["id"] for entity in diff["entities"]["added"]] == [SQS_STREAM]
    assert {rel["id"] for rel in diff["relationships"]["removed"]} == {KAFKA_PUBLISH, "relationship-88195dc3f65129be"}
    assert diff["conflicts"] == {"appeared": [], "disappeared": []}
    assert diff["invalid_assumptions"] == {"appeared": [], "disappeared": []}
    assert [decision["id"] for decision in diff["affected_decisions"]] == [EVENT_TRANSPORT]
    [item] = diff["impact"]["items"]
    assert (item["type"], item["id"], item["change"]) == ("entity", KAFKA_STREAM, "removed")
    [dependent] = item["dependents"]
    assert dependent["entity_id"] == ORDER_SERVICE and dependent["path"] == [ORDER_SERVICE, KAFKA_PUBLISH, KAFKA_STREAM]
    # Order Service lost publishes_to Kafka stream, but the SQS option rewires it to the SQS stream.
    assert dependent["present_after"] is True and dependent["points_at_missing"] is False and dependent["rewired"] is True
    assert dependent["missing_endpoints"] == [{"relationship_id": KAFKA_PUBLISH, "kind": "publishes_to", "missing_entity_id": KAFKA_STREAM, "status": "rewired", "rewired_to": [{"relationship_id": SQS_PUBLISH, "to": SQS_STREAM}]}]
    assert diff["receipt"]["selections"]["after"][EVENT_TRANSPORT] == SQS_OPTION

    # Arbitrary pair, not only versus the base: SQS back to Kafka mirrors the switch.
    back = service.diff_scenarios({EVENT_TRANSPORT: SQS_OPTION}, {EVENT_TRANSPORT: KAFKA_OPTION})
    assert [entity["id"] for entity in back["entities"]["removed"]] == [SQS_STREAM]
    assert [item["id"] for item in back["impact"]["items"]] == [SQS_STREAM]
    unchanged = service.diff_scenarios({EVENT_TRANSPORT: KAFKA_OPTION}, None)
    assert unchanged["selection_changes"] == [] and unchanged["impact"]["items"] == [] and unchanged["affected_decisions"] == []


def test_rest_diff_and_resolve_expose_impact_and_receipt(repo: Path, tmp_path: Path) -> None:
    client = TestClient(create_app(service_for(repo, tmp_path / "cache")))
    diff = client.post("/api/v1/scenarios/diff", json={"after_selections": {EVENT_TRANSPORT: SQS_OPTION}})
    assert diff.status_code == 200
    assert diff.json()["impact"]["items"][0]["id"] == KAFKA_STREAM
    resolved = client.post("/api/v1/scenarios/resolve", json={"selections": {EVENT_TRANSPORT: SQS_OPTION}}).json()
    assert resolved["impact"] == diff.json()["impact"]
    assert resolved["receipt"] == resolved["graph"]["receipt"]
    assert resolved["receipt"]["selections"][EVENT_TRANSPORT] == SQS_OPTION
    graph = client.get("/api/v1/graph").json()
    assert graph["scenario"]["impact"]["items"] == []
    assert graph["receipt"]["digest"] != resolved["receipt"]["digest"]
    search = client.post("/api/v1/search", json={"query": "Why Kafka?"}).json()
    assert search["receipt"]["request"] == {"query": "Why Kafka?"}
    assert search["receipt"]["components"]["records"] == graph["receipt"]["components"]["records"]


def test_graph_json_annotations_are_opt_out_and_skip_impact_at_repository_selections(repo: Path, tmp_path: Path) -> None:
    service = service_for(repo, tmp_path / "cache")
    lean = service.graph_json(annotate=False)
    assert "receipt" not in lean and "impact" not in lean["scenario"]
    full = service.graph_json({EVENT_TRANSPORT: KAFKA_OPTION})
    assert full["scenario"]["impact"]["items"] == []
    stripped = {key: value for key, value in full.items() if key != "receipt"}
    stripped["scenario"] = {key: value for key, value in full["scenario"].items() if key != "impact"}
    assert stripped == lean
    assert "receipt" not in service.entity_detail(ORDER_SERVICE)


def test_mcp_diff_scenarios_tool(repo: Path, tmp_path: Path) -> None:
    service = service_for(repo, tmp_path / "cache")
    server = create_mcp_server(lambda: service)

    async def exercise() -> tuple[set[str], dict]:
        tools = {tool.name for tool in await server.list_tools()}
        result = await server.call_tool("diff_scenarios", {"after_selections": {EVENT_TRANSPORT: SQS_OPTION}})
        return tools, result[1] if isinstance(result, tuple) else json.loads(result[0].text)

    tools, payload = asyncio.run(exercise())
    payload = payload.get("result", payload)
    assert "diff_scenarios" in tools and len(tools) == 5
    assert payload == service.diff_scenarios(None, {EVENT_TRANSPORT: SQS_OPTION})


def test_receipt_is_stable_and_tracks_reviews_evidence_and_selections(repo: Path, tmp_path: Path) -> None:
    service = service_for(repo, tmp_path / "cache-a")
    digest = service.graph_json()["receipt"]["digest"]
    selected = service.graph_json({EVENT_TRANSPORT: KAFKA_OPTION})["receipt"]
    assert selected["digest"] == digest, "an explicit default selection resolves to the same inputs"

    # Another service, another cache, another process, after an index rebuild: same receipt.
    other = service_for(repo, tmp_path / "cache-b")
    other.rebuild_indexes()
    assert other.graph_json()["receipt"]["digest"] == digest
    shutil.rmtree(tmp_path / "cache-a")
    assert service_for(repo, tmp_path / "cache-a").graph_json()["receipt"]["digest"] == digest
    process = subprocess.run([sys.executable, "-c", RECEIPT_SCRIPT, str(repo), str(tmp_path / "cache-c"), "{}"], capture_output=True, text=True, check=True)
    assert process.stdout.strip() == digest

    switched = service.graph_json({EVENT_TRANSPORT: SQS_OPTION})["receipt"]
    assert switched["digest"] != digest
    assert switched["components"]["records"] == selected["components"]["records"]
    assert switched["components"]["selections"] != selected["components"]["selections"]

    claim_id = next(path.stem for path in sorted((repo / ".decision" / "claims").glob("*.yaml")) if yaml.safe_load(path.read_text())["epistemic_state"] == "inferred")
    service.review_claim(claim_id, "confirmed")
    reviewed = service.graph_json()["receipt"]
    assert reviewed["digest"] != digest
    assert reviewed["components"]["review_heads"] != selected["components"]["review_heads"]

    evidence_path = sorted((repo / ".decision" / "evidence").glob("*.yaml"))[0]
    record = yaml.safe_load(evidence_path.read_text())
    record["text"] += " Edited."
    record["location"]["normalized_passage_sha256"] = passage_hash(record["text"])
    evidence_path.write_text(yaml.safe_dump(record, sort_keys=False))
    edited = service.graph_json()["receipt"]
    assert edited["digest"] not in {digest, reviewed["digest"]}
    assert edited["components"]["evidence_anchors"] != reviewed["components"]["evidence_anchors"]
    assert edited["components"]["review_heads"] == reviewed["components"]["review_heads"]


def test_rewiring_counts_only_edges_written_by_the_switched_decision_that_references_the_lost_target() -> None:
    """R1: when several decisions switch, a same-kind edge from an unrelated decision must not hide a dangling dependency."""
    entities = {name: Entity(name, "service", name.upper()) for name in ("svc", "old", "side", "new")}
    drop_old = Option("opt-drop", "Drop", "", {"operations": [{"op": "remove_entity", "entity": {"id": "old"}}]})
    keep_old = Option("opt-keep", "Keep", "", {"operations": []})
    side_edge = Option("opt-side", "Side", "", {"operations": [{"op": "add_relationship", "relationship": {"id": "r-side", "from": "svc", "to": "side", "kind": "calls"}}]})
    no_side = Option("opt-none", "None", "", {"operations": []})
    move = Option("opt-move", "Move", "", {"operations": [{"op": "remove_entity", "entity": {"id": "old"}}, {"op": "add_relationship", "relationship": {"id": "r-new", "from": "svc", "to": "new", "kind": "calls"}}]})
    decisions = [Decision("d-old", "Old", "decided", "", "opt-keep", [keep_old, drop_old, move]), Decision("d-side", "Side", "decided", "", "opt-none", [no_side, side_edge])]
    before = ResolvedScenario({"d-old": "opt-keep", "d-side": "opt-none"}, Graph(entities, {"r-old": Relationship("r-old", "svc", "old", "calls")}), [], [])
    remaining = {key: value for key, value in entities.items() if key != "old"}

    unrelated = ResolvedScenario({"d-old": "opt-drop", "d-side": "opt-side"}, Graph(remaining, {"r-side": Relationship("r-side", "svc", "side", "calls")}), [], [])
    [svc] = diff_resolved_scenarios(before, unrelated, decisions)["impact"]["items"][0]["dependents"]
    assert svc["missing_endpoints"][0]["status"] == "dangling" and svc["points_at_missing"] is True and svc["rewired"] is False
    assert downstream_impact(before.graph, unrelated.graph)["items"][0]["dependents"][0]["rewired"] is True, "without provenance the side edge looks like a rewire"

    moved = ResolvedScenario({"d-old": "opt-move", "d-side": "opt-side"}, Graph(remaining, {"r-side": Relationship("r-side", "svc", "side", "calls"), "r-new": Relationship("r-new", "svc", "new", "calls")}), [], [])
    [svc] = diff_resolved_scenarios(before, moved, decisions)["impact"]["items"][0]["dependents"]
    assert svc["missing_endpoints"] == [{"relationship_id": "r-old", "kind": "calls", "missing_entity_id": "old", "status": "rewired", "rewired_to": [{"relationship_id": "r-new", "to": "new"}]}]


def test_rewiring_filter_applies_to_each_lost_edge_of_one_source() -> None:
    """A source that loses two edges gets each one judged against its own missing target."""
    entities = {name: Entity(name, "service", name.upper()) for name in ("svc", "a", "b", "new")}
    before = Graph(entities, {"r-a": Relationship("r-a", "svc", "a", "calls"), "r-b": Relationship("r-b", "svc", "b", "calls")})
    after = Graph({"svc": entities["svc"], "new": entities["new"]}, {"r-new": Relationship("r-new", "svc", "new", "calls")})
    impact = downstream_impact(before, after, replacements={"a": {"r-new"}})
    [svc] = impact["items"][0]["dependents"]
    assert [(item["missing_entity_id"], item["status"]) for item in svc["missing_endpoints"]] == [("a", "rewired"), ("b", "dangling")]
    assert svc["rewired"] is True and svc["points_at_missing"] is True


def test_depth_one_dependents_of_removed_relationships_and_replaced_entities_lose_no_endpoint() -> None:
    """The UI labels these dependents "Direct": their own edge is the changed element, yet no endpoint goes missing."""
    entities = {name: Entity(name, "service", name.upper()) for name in ("a", "b", "c")}
    before = Graph(entities, {"r1": Relationship("r1", "a", "b", "calls"), "r2": Relationship("r2", "c", "a", "calls")})
    after = Graph(dict(entities), {"r2": before.relationships["r2"]})
    [removed] = downstream_impact(before, after)["items"]
    assert (removed["type"], removed["id"], removed["change"]) == ("relationship", "r1", "removed")
    [source, upstream] = removed["dependents"]
    assert (source["entity_id"], source["depth"], source["path"]) == ("a", 1, ["a", "r1", "b"])
    assert source["missing_endpoints"] == [] and not source["points_at_missing"] and not source["rewired"]
    assert (upstream["entity_id"], upstream["depth"]) == ("c", 2)

    renamed = Graph({**entities, "b": Entity("b", "service", "B v2")}, dict(before.relationships))
    [replaced] = downstream_impact(before, renamed)["items"]
    assert (replaced["type"], replaced["id"], replaced["change"]) == ("entity", "b", "replaced")
    direct = replaced["dependents"][0]
    assert (direct["entity_id"], direct["depth"], direct["path"]) == ("a", 1, ["a", "r1", "b"])
    assert direct["missing_endpoints"] == [] and direct["present_after"]


def test_replay_requirement_is_not_yet_surfaced(repo: Path, tmp_path: Path) -> None:
    """Pins a known gap tracked in README "Up next": scenario comparison ignores capability requirements.

    The event-transport source says the stream must support replay and that SQS needs extra work to replay. Human claims
    can record that as requires/provides/lacks_capability, but no output reports the unmet requirement after Kafka -> SQS.
    Replace this test when capability checking lands.
    """
    fulfillment = "entity-779ab6fab932e39b"
    service = service_for(repo, tmp_path / "cache")
    baseline = service.diff_scenarios(None, {EVENT_TRANSPORT: SQS_OPTION})

    human = {"epistemic_state": "asserted", "confidence": 1.0, "evidence": [], "reviewer": "human", "reviewed_at": "2026-10-16T00:00:00+00:00"}
    service.repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "capability-event-replay", "kind": "capability", "name": "Event replay", **human})
    claims = [
        ("claim-fulfillment-requires-replay", fulfillment, "requires_capability"),
        ("claim-kafka-provides-replay", KAFKA_STREAM, "provides_capability"),
        ("claim-sqs-lacks-replay", SQS_STREAM, "lacks_capability"),
    ]
    for claim_id, subject, predicate in claims:
        service.repository.save("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": claim_id, "subject": subject, "predicate": predicate, "object": "capability-event-replay", **human})

    stored = {record["id"]: record for record in service_for(repo, tmp_path / "cache-2").repository.records("claims")}
    assert {(stored[claim_id]["subject"], stored[claim_id]["predicate"]) for claim_id, _, _ in claims} == {(subject, predicate) for _, subject, predicate in claims}
    assert "capability-event-replay" in {entity["id"] for entity in service.graph_json()["entities"]}, "records pass read-time validation"

    diff = service.diff_scenarios(None, {EVENT_TRANSPORT: SQS_OPTION})
    assert diff["invalid_assumptions"] == baseline["invalid_assumptions"] == {"appeared": [], "disappeared": []}
    assert diff["conflicts"] == baseline["conflicts"]
    assert diff["impact"] == baseline["impact"]
    [dependent] = diff["impact"]["items"][0]["dependents"]
    assert dependent["entity_id"] == ORDER_SERVICE and dependent["rewired"] is True, "still reported rewired, with no replay warning"
    assert all(fulfillment not in (dep["entity_id"] for dep in item["dependents"]) for item in diff["impact"]["items"])
    assert diff["receipt"]["digest"] != baseline["receipt"]["digest"], "the claims are inputs, yet nothing in the output reflects them"

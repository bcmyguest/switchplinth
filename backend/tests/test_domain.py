from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys

import pytest
import yaml

from switchplinth.domain import Claim, Decision, DomainError, Entity, Graph, Option, Relationship, compile_scenario, effective_aliases, effective_claims, identity_projection, load_yaml, stable_id
from switchplinth.repository import PortableRepository, discover_markdown, passages, relocate_evidence, source_identity
from switchplinth.service import DecisionService
from switchplinth.store import SearchIndex, hashed_embedding

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(("interrupt_point", "exit_code", "expected_version"), [("before", 71, "old"), ("after", 72, "new")])
def test_save_process_interruption_publishes_old_or_new_record_only(
    tmp_path: Path, interrupt_point: str, exit_code: int, expected_version: str
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    repository = PortableRepository(root)
    original = {"schema_version": "decision/v1", "record_type": "entity", "id": "target", "kind": "service", "name": "Old target"}
    replacement = {**original, "name": "New target"}
    unrelated = {"schema_version": "decision/v1", "record_type": "entity", "id": "unrelated", "kind": "service", "name": "Untouched record"}
    target_path = repository.save("entities", original)
    unrelated_path = repository.save("entities", unrelated)
    original_bytes = target_path.read_bytes()
    unrelated_bytes = unrelated_path.read_bytes()
    replacement_bytes = yaml.safe_dump(replacement, sort_keys=False, allow_unicode=True).encode("utf-8")

    child_script = """
import os
import sys
from pathlib import Path
import switchplinth.repository as repository_module
from switchplinth.repository import PortableRepository

root = Path(sys.argv[1])
interrupt_point = sys.argv[2]
exit_code = int(sys.argv[3])
replace = os.replace

def interrupting_replace(source, destination):
    if interrupt_point == "before":
        os._exit(exit_code)
    replace(source, destination)
    if interrupt_point == "after":
        os._exit(exit_code)

repository_module.os.replace = interrupting_replace
PortableRepository(root).save(
    "entities",
    {"schema_version": "decision/v1", "record_type": "entity", "id": "target", "kind": "service", "name": "New target"},
)
"""
    child = subprocess.run(
        [sys.executable, "-c", child_script, str(root), interrupt_point, str(exit_code)],
        cwd=ROOT / "backend",
        capture_output=True,
        check=False,
        timeout=15,
    )

    assert child.returncode == exit_code, child.stderr.decode("utf-8", errors="replace")
    restarted = PortableRepository(root)
    loaded = {record["id"]: record for record in restarted.records("entities")}
    assert loaded["target"] == (original if expected_version == "old" else replacement)
    assert target_path.read_bytes() == (original_bytes if expected_version == "old" else replacement_bytes)
    assert unrelated_path.read_bytes() == unrelated_bytes


def test_human_claims_override_inference_and_rejection_is_sticky() -> None:
    inferred = Claim("i", "orders", "uses", "queue", "inferred", 0.8, ["e1"])
    confirmed = Claim("c", "orders", "uses", "queue", "confirmed", 1.0)
    assert [claim.id for claim in effective_claims([inferred, confirmed])] == ["c"]
    rejected = Claim("r", "orders", "uses", "queue", "rejected", 1.0)
    assert effective_claims([inferred, rejected]) == []
    corrected = Claim("c2", "orders", "uses", "queue", "confirmed", 1.0, supersedes=["r"])
    assert [claim.id for claim in effective_claims([inferred, rejected, corrected])] == ["c2"]
    inferred_alias = {"id": "alias-inferred", "entity_id": "kafka", "name": "kfk", "epistemic_state": "inferred"}
    rejected_alias = {"id": "alias-rejected", "entity_id": "kafka", "name": "kfk", "epistemic_state": "rejected"}
    corrected_alias = {"id": "alias-corrected", "entity_id": "kafka", "name": "kfk", "epistemic_state": "confirmed", "supersedes": ["alias-rejected"]}
    assert effective_aliases([inferred_alias, rejected_alias, corrected_alias]) == [corrected_alias]


def test_identity_links_group_symmetrically_and_positive_cycles_are_harmless() -> None:
    entities = {key: Entity(key, "service", key.title()) for key in ("orders", "worker", "processor")}
    claims = [
        Claim("link-1", "worker", "same_entity_as", "orders", "confirmed", 1),
        Claim("link-2", "processor", "same_entity_as", "worker", "asserted", 1),
        Claim("link-3", "orders", "same_entity_as", "processor", "confirmed", 1),
    ]

    projected = identity_projection(entities, claims)

    assert projected["identity_groups"] == [{"entity_ids": ["orders", "processor", "worker"]}]
    assert projected["identity_conflicts"] == []


def test_identity_projection_surfaces_unsuperseded_and_transitive_rejection_conflicts() -> None:
    entities = {key: Entity(key, "service", key.title()) for key in ("a", "b", "c", "d")}
    claims = [
        Claim("ab-confirm", "a", "same_entity_as", "b", "confirmed", 1),
        Claim("ab-reject", "b", "same_entity_as", "a", "rejected", 1),
        Claim("bc-confirm", "b", "same_entity_as", "c", "confirmed", 1),
        Claim("ac-reject", "a", "same_entity_as", "c", "rejected", 1),
        Claim("cd-confirm", "c", "same_entity_as", "d", "confirmed", 1),
    ]

    projected = identity_projection(entities, claims)

    assert projected["identity_groups"] == []
    assert {conflict["type"] for conflict in projected["identity_conflicts"]} == {"conflicting_judgments", "rejected_transitive_path"}
    assert any(conflict["entity_ids"] == ["a", "c"] for conflict in projected["identity_conflicts"])
    assert all("d" in conflict.get("component_entity_ids", conflict["entity_ids"]) for conflict in projected["identity_conflicts"] if conflict["type"] == "rejected_transitive_path")


@pytest.mark.parametrize(
    ("subject", "object_id", "kind_b", "message"),
    [
        ("a", "a", "service", "distinct"),
        ("a", "missing", "service", "existing entity"),
        ("a", "b", "queue", "same entity kind"),
    ],
)
def test_identity_claim_endpoint_validation_on_save_load_and_review(tmp_path: Path, subject: str, object_id: str, kind_b: str, message: str) -> None:
    repository, service = make_minimal_repository(tmp_path / "repo")
    repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "a", "kind": "service", "name": "A"})
    if object_id != "missing" and object_id != "a":
        repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "b", "kind": kind_b, "name": "B"})
    claim = {"schema_version": "decision/v1", "record_type": "claim", "id": "bad-link", "subject": subject, "predicate": "same_entity_as", "object": object_id, "epistemic_state": "confirmed", "confidence": 1, "evidence": []}

    with pytest.raises(DomainError, match=message):
        repository.save("claims", claim)
    assert not (repository.overlay / "claims" / "bad-link.yaml").exists()

    # Portable records edited outside the application are validated on load too.
    claim_path = repository.overlay / "claims" / "bad-link.yaml"
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    claim_path.write_text(yaml.safe_dump(claim), encoding="utf-8")
    with pytest.raises(DomainError, match=message):
        repository.records("claims")
    with pytest.raises(DomainError, match=message):
        service.review_claim("bad-link", "confirmed")


def test_identity_review_chain_supersedes_prior_judgments_and_graph_api_returns_groups(tmp_path: Path) -> None:
    from switchplinth.api import create_app

    repository, service = make_minimal_repository(tmp_path / "repo")
    for entity_id in ("a", "b"):
        repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": entity_id, "kind": "service", "name": entity_id.upper()})
    (tmp_path / "repo/docs").mkdir()
    (tmp_path / "repo/docs/source.md").write_text("This source explains that the services represent the same system component.", encoding="utf-8")
    evidence = save_source_evidence(repository, tmp_path / "repo", "docs/source.md")[0]
    repository.save("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": "inferred-link", "subject": "a", "predicate": "same_entity_as", "object": "b", "epistemic_state": "inferred", "confidence": 0.8, "evidence": [evidence["id"]]})
    (tmp_path / "repo/docs/second.md").write_text("A separate source passage describes entity B.", encoding="utf-8")
    second_evidence = save_source_evidence(repository, tmp_path / "repo", "docs/second.md")[0]
    entity_b = next(record for record in repository.records_unchecked("entities") if record["id"] == "b")
    repository.save("entities", {**entity_b, "evidence": [second_evidence["id"]]})
    repository.save("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": "mention-b", "subject": "b", "predicate": "mentioned_in", "object": "docs/second.md", "epistemic_state": "inferred", "confidence": 0.9, "evidence": [second_evidence["id"]]})
    # Human review is appended and keeps the original claim in the review chain.
    rejected = service.review_claim("inferred-link", "rejected")
    assert rejected["reviewed_claim"] == "inferred-link"
    assert service.graph_json()["identity_groups"] == []
    confirmed = service.review_claim(rejected["id"], "confirmed")
    assert rejected["id"] in confirmed["supersedes"]
    assert service.graph_json()["identity_groups"] == [{"entity_ids": ["a", "b"]}]
    detail = service.entity_detail("a")
    assert {record["id"] for record in detail["evidence"]} >= {evidence["id"], second_evidence["id"]}

    app = create_app(service)
    graph_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/graph")
    response = graph_route.endpoint()
    assert response["identity_groups"] == [{"entity_ids": ["a", "b"]}]
    assert "identity_suggestions" in response and "identity_conflicts" in response


def test_identity_suggestions_are_read_time_only_and_do_not_restore_absent_option_entities(tmp_path: Path) -> None:
    repository, service = make_minimal_repository(tmp_path / "repo")
    for entity_id in ("first", "second"):
        repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": entity_id, "kind": "service", "name": "Same Service"})
    option_entity = {"id": "option-only", "kind": "service", "name": "Same Service"}
    repository.save("decisions", {
        "schema_version": "decision/v1", "record_type": "decision", "id": "decision-option-entity",
        "title": "Optional service", "status": "proposed", "selected_option": None,
        "options": [{"id": "option-add", "title": "Add", "delta": {"base": "architecture", "operations": [{"op": "add_entity", "entity": option_entity}]}}],
    })

    base = service.graph_json()
    selected = service.graph_json({"decision-option-entity": "option-add"})

    assert {entity["id"] for entity in base["entities"]} == {"first", "second"}
    assert all("option-only" not in suggestion["entity_ids"] for suggestion in base["identity_suggestions"])
    assert any(suggestion["source"] == "exact_name" and suggestion["entity_ids"] == ["first", "second"] for suggestion in base["identity_suggestions"])
    assert {entity["id"] for entity in selected["entities"]} == {"first", "second", "option-only"}
    assert any("option-only" in suggestion["entity_ids"] for suggestion in selected["identity_suggestions"])


def test_entity_detail_exposes_option_alternatives_through_unresolved_exact_name_candidate(tmp_path: Path) -> None:
    repository, service = make_minimal_repository(tmp_path / "repo")
    repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "base-redis", "kind": "datastore", "name": "Redis"})
    repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "datastore-redis", "kind": "datastore", "name": "Redis"})
    decision_id = "decision-redis-option"
    option_id = "option-redis"
    repository.save("decisions", {
        "schema_version": "decision/v1", "record_type": "decision", "id": decision_id,
        "title": "Order database", "status": "proposed", "selected_option": option_id,
        "options": [{"id": option_id, "title": "Redis", "delta": {"base": "architecture", "operations": [{"op": "add_entity", "entity": {"id": "datastore-redis", "kind": "datastore", "name": "Redis"}}]}}],
    })

    detail = service.entity_detail("base-redis", {decision_id: option_id})
    visible_graph = service.graph_json({decision_id: option_id})
    redis_ids = {entity["id"] for entity in visible_graph["entities"] if entity["name"].casefold() == "redis"}
    assert redis_ids == {"base-redis", "datastore-redis"}
    assert visible_graph["identity_groups"] == []
    assert [decision["id"] for decision in detail["decisions"]] == [decision_id]
    assert detail["identity_suggestions"][0]["source"] == "exact_name"

    repository.save("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": "human-reject-redis", "subject": "base-redis", "predicate": "same_entity_as", "object": "datastore-redis", "epistemic_state": "rejected", "confidence": 1, "evidence": []})
    rejected_detail = service.entity_detail("base-redis", {decision_id: option_id})
    assert rejected_detail["decisions"] == []


def test_food_delivery_bootstrap_keeps_repeat_references_and_contextual_databases_distinct(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    module_path = ROOT / "fixtures/food-delivery/bootstrap.py"
    spec = importlib.util.spec_from_file_location("food_delivery_bootstrap", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.bootstrap(tmp_path / "food-delivery")
    graph = result["graph"]
    assert sum(entity["id"] == result["order_service_id"] for entity in graph["entities"]) == 1
    assert sum(entity["id"] == result["kafka_id"] for entity in graph["entities"]) == 1
    assert len(result["postgres_ids"]) == 2
    assert result["scan"]["candidate_decision_count"] == 7
    assert len(graph["decisions"]) == 7
    assert graph["identity_groups"] == []
    assert len([record for record in graph["evidence"] if "Order Service" in record["text"]]) >= 2
    assert any(entity["id"] == "datastore-postgres-reporting" and entity["description"] for entity in graph["entities"])
    aliases = {alias["name"]: alias for alias in graph["aliases"]}
    assert len(aliases["kafka"]["evidence"]) >= 2
    assert aliases["orders service"]["evidence"]
    order_service_claims = [claim for claim in graph["claims"] if claim["subject"] == result["order_service_id"] and claim["predicate"] == "mentioned_in"]
    order_service_evidence = {evidence_id for claim in order_service_claims for evidence_id in claim["evidence"]}
    assert len(order_service_evidence) >= 2
    extracted = {decision["title"]: decision for decision in graph["decisions"]}
    expected_options = {
        "Event delivery for food orders": {"Apache Kafka", "Amazon SQS"},
        "Payment retry delivery": {"Amazon SQS", "Apache Kafka"},
        "Courier dispatch runtime": {"Kubernetes", "Fixed worker pool backed by Amazon SQS"},
        "RFC: durable order data": {"PostgreSQL", "Redis"},
        "RFC: restaurant and menu reads": {"Redis", "PostgreSQL"},
        "Order placement and restaurant reservation": {"Accept, then fulfill asynchronously", "Wait for reservation during checkout"},
        "RFC: courier and restaurant availability": {"Redis", "Reporting PostgreSQL database queries"},
    }
    evidence_by_id = {item["id"]: item for item in graph["evidence"]}
    source_suffixes = {
        "Event delivery for food orders": "decisions/event-transport.md",
        "Payment retry delivery": "decisions/payment-retries.md",
        "Courier dispatch runtime": "design/courier-dispatch.md",
        "RFC: durable order data": "rfcs/order-data.md",
        "RFC: restaurant and menu reads": "rfcs/restaurant-menu-cache.md",
        "Order placement and restaurant reservation": "design/order-placement.md",
        "RFC: courier and restaurant availability": "rfc/geo-availability.md",
    }
    expected_relationship_kinds = {
        "Event delivery for food orders": {"publishes_to"},
        "Payment retry delivery": {"queues"},
        "Courier dispatch runtime": {"runs_on", "dispatches_with", "consumes_from"},
        "RFC: durable order data": {"stores_in"},
        "RFC: restaurant and menu reads": set(),
        "Order placement and restaurant reservation": {"submits_reservation_async", "publishes_accepted_order", "waits_for_reservation"},
        "RFC: courier and restaurant availability": {"reads_from"},
    }
    expected_anchors = {
        "Event delivery for food orders": ("replay", "Amazon SQS"),
        "Payment retry delivery": ("Amazon SQS", "Apache Kafka"),
        "Courier dispatch runtime": ("Kubernetes", "Amazon SQS"),
        "RFC: durable order data": ("PostgreSQL", "Redis"),
        "RFC: restaurant and menu reads": ("Redis", "PostgreSQL"),
        "Order placement and restaurant reservation": ("asynchronous reservation", "synchronous reservation"),
        "RFC: courier and restaurant availability": ("Redis", "PostgreSQL"),
    }
    expected_option_anchors = {
        "Event delivery for food orders": {"Apache Kafka": "replay", "Amazon SQS": "Amazon SQS"},
        "Payment retry delivery": {"Amazon SQS": "managed retries", "Apache Kafka": "Apache Kafka"},
        "Courier dispatch runtime": {"Kubernetes": "Kubernetes", "Fixed worker pool backed by Amazon SQS": "fixed worker pool"},
        "RFC: durable order data": {"PostgreSQL": "PostgreSQL", "Redis": "Redis"},
        "RFC: restaurant and menu reads": {"Redis": "Redis", "PostgreSQL": "PostgreSQL"},
        "Order placement and restaurant reservation": {"Accept, then fulfill asynchronously": "asynchronous reservation", "Wait for reservation during checkout": "synchronous reservation"},
        "RFC: courier and restaurant availability": {"Redis": "Redis", "Reporting PostgreSQL database queries": "PostgreSQL"},
    }
    for title, names in expected_options.items():
        decision = extracted[title]
        assert {option["title"] for option in decision["options"]} == names
        for option in decision["options"]:
            assert option["evidence"]
            anchors = expected_anchors[title]
            allowed_sources = [source_suffixes[title]]
            if title == "RFC: courier and restaurant availability" and option["title"].startswith("Reporting PostgreSQL"):
                allowed_sources.append("design/reporting.md")
            assert all(any(evidence_by_id[reference]["source"]["path"].endswith(suffix) for suffix in allowed_sources) for reference in option["evidence"])
            assert any(anchor.casefold() in " ".join(evidence_by_id[reference]["text"].casefold() for reference in option["evidence"]) for anchor in anchors)
            assert expected_option_anchors[title][option["title"]].casefold() in " ".join(evidence_by_id[reference]["text"].casefold() for reference in option["evidence"])
            operations = option["delta"]["operations"]
            relationship_kinds = {operation["relationship"]["kind"] for operation in operations if operation.get("op") == "add_relationship"}
            semantic_kinds = relationship_kinds - {"implemented_by"}
            assert semantic_kinds <= expected_relationship_kinds[title]
            assert bool(semantic_kinds) is (title != "RFC: restaurant and menu reads")
            assert all(operation.get("op") in {"add_entity", "add_relationship"} for operation in operations)
            resources = [operation["entity"]["id"] for operation in operations if operation.get("op") == "add_entity"]
            resource_free = title == "Order placement and restaurant reservation" or (title == "RFC: courier and restaurant availability" and option["title"].startswith("Reporting PostgreSQL"))
            expected_resource_count = 0 if resource_free else 2 if title == "Courier dispatch runtime" and option["title"].startswith("Fixed worker pool") else 1
            assert len(resources) == len(set(resources)) == expected_resource_count
            if title == "Courier dispatch runtime" and option["title"].startswith("Fixed worker pool"):
                resource_names = {operation["entity"]["name"] for operation in operations if operation.get("op") == "add_entity"}
                assert resource_names == {"Fixed dispatch worker pool", "Dispatch job queue (Fixed worker pool backed by Amazon SQS)"}
            if title == "RFC: courier and restaurant availability" and option["title"].startswith("Reporting PostgreSQL"):
                assert any(operation.get("relationship", {}).get("to") == "datastore-postgres-reporting" for operation in operations)
            support_text = " ".join(evidence_by_id[reference]["text"].casefold() for reference in option["evidence"])
            actor_names = {
                "Event delivery for food orders": "Order Service",
                "Payment retry delivery": "Payments Service",
                "Courier dispatch runtime": "Dispatch workers",
                "RFC: durable order data": "Order Service",
                "Order placement and restaurant reservation": "Order Service",
                "RFC: courier and restaurant availability": "dispatch workflow",
            }
            expected_actor = actor_names.get(title)
            if expected_actor and any(operation.get("op") == "add_relationship" and operation["relationship"]["kind"] != "implemented_by" for operation in operations):
                assert expected_actor.casefold() in support_text
            if title == "RFC: restaurant and menu reads":
                assert all(operation["relationship"]["kind"] == "implemented_by" for operation in operations if operation.get("op") == "add_relationship")
    assert not ({"PostgreSQL", "Redis"} & {option["title"] for option in extracted["Event delivery for food orders"]["options"]})
    assert not ({"Apache Kafka", "Amazon SQS", "Kubernetes"} & {option["title"] for option in extracted["RFC: durable order data"]["options"]})
    assert {option["title"] for option in extracted["RFC: courier and restaurant availability"]["options"]} != {"Reporting PostgreSQL database queries"}

    service = module.DecisionService(tmp_path / "food-delivery", tmp_path / ".food-delivery-decision-cache")
    option_ids = {title: {option["title"]: option["id"] for option in decision["options"]} for title, decision in extracted.items()}
    combinations = (
        {"Event delivery for food orders": "Amazon SQS", "Payment retry delivery": "Amazon SQS"},
        {"RFC: durable order data": "Redis", "RFC: restaurant and menu reads": "Redis"},
        {"Event delivery for food orders": "Apache Kafka", "Payment retry delivery": "Apache Kafka"},
        {"RFC: durable order data": "PostgreSQL", "RFC: restaurant and menu reads": "PostgreSQL"},
    )
    for combination in combinations:
        selections = {decision["id"]: decision["selected_option"] for decision in graph["decisions"]}
        for title, option_title in combination.items():
            selections[extracted[title]["id"]] = option_ids[title][option_title]
        resolved = service.graph_json(selections)
        assert resolved["scenario"]["conflicts"] == []
        assert resolved["scenario"]["invalid_assumptions"] == []

def test_food_delivery_ordinary_scan_extracts_seven_decisions_and_reporting_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import patch

    root = tmp_path / "food-docs"
    source_docs = ROOT / "fixtures/food-delivery/docs"
    for source in source_docs.rglob("*.md"):
        destination = root / source.relative_to(source_docs)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    service = DecisionService(root, tmp_path / "cache")
    assert not any(record["id"] == "datastore-postgres-reporting" for record in service.repository.records_unchecked("entities"))

    with patch("switchplinth.service.qdrant_rebuild", return_value="offline test"):
        scan = service.scan()

    graph = service.graph_json()
    assert scan["candidate_decision_count"] == 7
    assert len(graph["decisions"]) == 7
    reporting = next(entity for entity in service.repository.records("entities") if entity["id"] == "datastore-postgres-reporting")
    reporting_evidence = next(record for record in graph["evidence"] if record["id"] in reporting["evidence"])
    assert reporting["name"] == "Analytics reporting PostgreSQL"
    assert reporting_evidence["source"]["path"] == "design/reporting.md"
    reporting_claims = [claim for claim in graph["claims"] if claim["subject"] == reporting["id"]]
    assert reporting_claims
    evidence_by_id = {record["id"]: record for record in graph["evidence"]}
    for claim in reporting_claims:
        assert claim["object"] == "design/reporting.md"
        assert all(evidence_by_id[evidence_id]["source"]["path"] == "design/reporting.md" for evidence_id in claim["evidence"])
    availability = next(decision for decision in graph["decisions"] if decision["title"] == "RFC: courier and restaurant availability")
    reporting_option = next(option for option in availability["options"] if option["title"] == "Reporting PostgreSQL database queries")
    assert any(operation.get("relationship", {}).get("to") == reporting["id"] for operation in reporting_option["delta"]["operations"])
    assert any(evidence_by_id[evidence_id]["source"]["path"] == "design/reporting.md" for evidence_id in reporting_option["evidence"])
    assert not graph["scenario"]["conflicts"]
    assert not graph["scenario"]["invalid_assumptions"]


def test_search_preserves_rejected_identity_history_for_conflicts_and_suggestions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository, service = make_minimal_repository(tmp_path / "repo")
    for entity_id in ("a", "b", "c"):
        repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": entity_id, "kind": "service", "name": "Same Service"})
    for claim_id, subject, object_id, state in (
        ("reject-ab", "a", "b", "rejected"),
        ("confirm-ac", "a", "c", "confirmed"),
        ("confirm-cb", "c", "b", "confirmed"),
    ):
        repository.save("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": claim_id, "subject": subject, "predicate": "same_entity_as", "object": object_id, "epistemic_state": state, "confidence": 1, "evidence": []})
    monkeypatch.setattr("switchplinth.service.qdrant_search", lambda *args, **kwargs: [])

    result = service.search("Same Service")

    assert any(conflict["type"] == "rejected_transitive_path" and conflict["entity_ids"] == ["a", "b"] for conflict in result["identity_conflicts"])
    assert not any(suggestion["source"] == "exact_name" and suggestion["entity_ids"] == ["a", "b"] for suggestion in result["identity_suggestions"])


def test_identity_review_and_correction_api_return_422_for_invalid_endpoints(tmp_path: Path) -> None:
    from fastapi import HTTPException

    from switchplinth.api import ClaimCorrectionRequest, ReviewRequest, create_app

    repository, service = make_minimal_repository(tmp_path / "repo")
    repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "a", "kind": "service", "name": "A"})
    repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "b", "kind": "service", "name": "B"})
    repository.save("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": "source-claim", "subject": "a", "predicate": "mentions", "object": "target", "epistemic_state": "confirmed", "confidence": 1, "evidence": []})
    app = create_app(service)
    correct_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/claims/{claim_id}/correct")

    with pytest.raises(HTTPException) as correction:
        correct_route.endpoint("source-claim", ClaimCorrectionRequest(subject="a", predicate="same_entity_as", object="missing"))
    assert correction.value.status_code == 422

    repository.save("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": "identity-claim", "subject": "a", "predicate": "same_entity_as", "object": "b", "epistemic_state": "confirmed", "confidence": 1, "evidence": []})
    (repository.overlay / "entities" / "b.yaml").unlink()
    review_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/claims/{claim_id}/review")
    with pytest.raises(HTTPException) as review:
        review_route.endpoint("identity-claim", ReviewRequest(epistemic_state="rejected"))
    assert review.value.status_code == 422


@pytest.mark.parametrize(
    ("entity_ids", "second_name", "second_kind", "message"),
    [
        (["a"], "Same Service", "service", "two entity IDs"),
        (["a", "a"], "Same Service", "service", "distinct"),
        (["a", "missing"], "Same Service", "service", "existing entities"),
        (["a", "b"], "Same Service", "queue", "same kind"),
        (["a", "b"], "Different Service", "service", "current exact-name candidate"),
    ],
)
def test_exact_identity_candidate_review_rejects_invalid_pairs(
    tmp_path: Path, entity_ids: list[str], second_name: str, second_kind: str, message: str
) -> None:
    repository, service = make_minimal_repository(tmp_path / "repo")
    repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "a", "kind": "service", "name": " Same   Service "})
    if entity_ids[-1] != "missing" and entity_ids[-1] != "a":
        repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "b", "kind": second_kind, "name": second_name})

    with pytest.raises(DomainError, match=message):
        service.review_exact_identity_candidate(entity_ids, "confirmed")
    claims_directory = repository.overlay / "claims"
    assert not claims_directory.exists() or not list(claims_directory.glob("*.yaml"))


@pytest.mark.parametrize("state", ["confirmed", "asserted", "rejected"])
def test_exact_identity_candidate_review_is_portable_idempotent_and_exposes_projection(tmp_path: Path, state: str) -> None:
    from switchplinth.api import ExactIdentityReviewRequest, create_app

    repository, service = make_minimal_repository(tmp_path / "repo")
    for entity_id, name in (("a", " Same   Service "), ("b", "same service")):
        repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": entity_id, "kind": "service", "name": name})
    app = create_app(service)
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/identity-candidates/review")
    request = ExactIdentityReviewRequest(entity_ids=["b", "a"], epistemic_state=state)

    response = route.endpoint(request)
    persisted = repository.records("claims")
    assert len(persisted) == 1
    claim = persisted[0]
    assert response["claim"] == claim
    assert claim["predicate"] == "same_entity_as"
    assert claim["epistemic_state"] == state
    assert claim["reviewer"] == "human"
    assert claim["evidence"] == []
    assert "source_path" not in claim
    assert "reviewed_claim" not in claim
    assert response["identity_groups"] == ([{"entity_ids": ["a", "b"]}] if state in {"confirmed", "asserted"} else [])
    assert response["identity_suggestions"] == ([{"source": "exact_name", "entity_ids": ["a", "b"], "name": "same service", "kind": "service", "evidence": [], "claim_id": claim["id"], "epistemic_state": "rejected"}] if state == "rejected" else [])
    assert response["identity_conflicts"] == []

    repeated = route.endpoint(request)
    assert repeated["claim"]["id"] == claim["id"]
    assert len(repository.records("claims")) == 1


def test_exact_identity_candidate_api_rejects_unknown_state(tmp_path: Path) -> None:
    from fastapi import HTTPException

    from switchplinth.api import ExactIdentityReviewRequest, create_app

    _, service = make_minimal_repository(tmp_path / "repo")
    app = create_app(service)
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/identity-candidates/review")

    with pytest.raises(HTTPException) as invalid_state:
        route.endpoint(ExactIdentityReviewRequest(entity_ids=["a", "b"], epistemic_state="inferred"))
    assert invalid_state.value.status_code == 422


def test_exact_identity_candidate_review_joins_inference_chain_and_supersedes_conflicting_judgments(tmp_path: Path) -> None:
    from switchplinth.api import ExactIdentityReviewRequest, create_app

    repository, service = make_minimal_repository(tmp_path / "repo")
    for entity_id, name in (("a", "Same Service"), ("b", "same  service")):
        repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": entity_id, "kind": "service", "name": name})
    (tmp_path / "repo/docs").mkdir()
    (tmp_path / "repo/docs/source.md").write_text("An evidence passage for the inferred identity claim.", encoding="utf-8")
    evidence = save_source_evidence(repository, tmp_path / "repo", "docs/source.md")[0]
    repository.save("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": "inferred-pair", "subject": "a", "predicate": "same_entity_as", "object": "b", "epistemic_state": "inferred", "confidence": 0.8, "evidence": [evidence["id"]]})
    repository.save("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": "opposing-human", "subject": "b", "predicate": "same_entity_as", "object": "a", "epistemic_state": "rejected", "confidence": 1, "evidence": []})
    repository.save("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": "positive-human", "subject": "a", "predicate": "same_entity_as", "object": "b", "epistemic_state": "confirmed", "confidence": 1, "evidence": []})
    app = create_app(service)
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/identity-candidates/review")

    response = route.endpoint(ExactIdentityReviewRequest(entity_ids=["a", "b"], epistemic_state="confirmed"))

    claim = response["claim"]
    all_claims = {record["id"]: record for record in repository.records("claims")}
    assert claim["reviewed_claim"] == "opposing-human"
    assert {"inferred-pair", "opposing-human", "positive-human"} <= set(claim["supersedes"])
    assert claim["evidence"] == []
    assert "source_path" not in claim
    assert all_claims["inferred-pair"]["evidence"] == [evidence["id"]]
    assert response["identity_groups"] == [{"entity_ids": ["a", "b"]}]
    assert response["identity_suggestions"] == []
    assert response["identity_conflicts"] == []


def test_scenario_option_delta_and_conflicting_writes() -> None:
    base = Graph({"orders": Entity("orders", "service", "Orders"), "worker": Entity("worker", "service", "Worker")})
    decision = Decision("messaging", "Messaging", "proposed", "", None, [
        Option("kafka", "Kafka", "", {"operations": [
            {"op": "add_entity", "entity": {"id": "kafka", "kind": "technology", "name": "Kafka"}, "expect": {"exists": False}},
            {"op": "add_relationship", "relationship": {"id": "orders-kafka", "from": "orders", "to": "kafka", "kind": "publishes_to"}},
        ]}),
        Option("sqs", "SQS", "", {"operations": [{"op": "add_entity", "entity": {"id": "sqs", "kind": "queue", "name": "SQS"}}]}),
    ])
    result = compile_scenario(base, [decision], {"messaging": "kafka"})
    assert result.graph.entities["kafka"].name == "Kafka"
    assert result.graph.relationships["orders-kafka"].target == "kafka"
    bad = compile_scenario(base, [decision], {"messaging": "kafka", "unknown": "sqs"})
    assert any("Unknown decision" in issue for issue in bad.conflicts)
    precondition = Decision("stale", "Stale", "proposed", "", None, [Option("add", "Add", "", {"operations": [{"op": "add_entity", "entity": {"id": "orders", "kind": "service", "name": "Orders"}, "expect": {"exists": False}}]})])
    assert any("Precondition failed" in issue for issue in compile_scenario(base, [precondition], {"stale": "add"}).conflicts)


def test_scenario_switch_reports_decisions_that_assume_removed_nodes() -> None:
    base = Graph({"orders": Entity("orders", "service", "Orders"), "kafka": Entity("kafka", "technology", "Kafka")})
    messaging = Decision("messaging", "Messaging", "decided", "", None, [
        Option("kafka", "Kafka", "", {"operations": []}),
        Option("sqs", "SQS", "", {"operations": [{"op": "remove_entity", "entity": {"id": "kafka"}}]}),
    ])
    downstream = Decision("events", "Event processing", "proposed", "", None, [
        Option("kafka-events", "Kafka event stream", "", {"operations": [{"op": "add_relationship", "relationship": {"id": "orders-kafka", "from": "orders", "to": "kafka", "kind": "publishes_to"}}]}),
    ])
    result = compile_scenario(base, [messaging, downstream], {"messaging": "sqs"})
    assert "events" in result.affected_decisions
    assert any("assumes removed" in issue and "kafka" in issue for issue in result.invalid_assumptions)


def test_anchor_relocates_after_line_shift_and_keeps_ambiguous_unresolved(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# Heading\n\nUnique passage with enough content to anchor safely.\n", encoding="utf-8")
    before = passages(source, tmp_path)[0]
    source.write_text("# Heading\n\nInserted note above it.\n\nUnique passage with enough content to anchor safely.\n", encoding="utf-8")
    moved = relocate_evidence(before, passages(source, tmp_path))
    assert moved.id == before.id
    assert moved.display_line > before.display_line
    source.write_text("# Heading\n\nUnique passage with enough content to anchor safely.\n\nUnique passage with enough content to anchor safely.\n", encoding="utf-8")
    unresolved = relocate_evidence(before, passages(source, tmp_path))
    assert unresolved.id == before.id
    assert unresolved.state == "unresolved"
    source.write_text("# Heading\n\nCompletely unrelated prose replaces the passage under this same heading.\n", encoding="utf-8")
    replaced = relocate_evidence(before, passages(source, tmp_path))
    assert replaced.id == before.id
    assert replaced.state == "unresolved"


def test_discovery_excludes_overlay_and_generated_markdown(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/source.md").write_text("A real source passage with enough text to index.", encoding="utf-8")
    for directory in (".decision", ".pytest_cache", "backend/.pytest_cache"):
        path = tmp_path / directory
        path.mkdir(parents=True)
        (path / "README.md").write_text("Generated or canonical metadata markdown must not be source.", encoding="utf-8")
    assert [path.relative_to(tmp_path).as_posix() for path in discover_markdown(tmp_path)] == ["docs/source.md"]


def fixture_repository(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / ".decision", tmp_path / ".decision")
    shutil.copytree(ROOT / "examples", tmp_path / "examples")
    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    for source in ROOT.glob("*.md"):
        shutil.copy(source, tmp_path / source.name)
    for evidence in PortableRepository(ROOT).records_unchecked("evidence"):
        source = ROOT / evidence["source"]["path"]
        if source.is_file():
            target = tmp_path / evidence["source"]["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, target)
    (tmp_path / "backend").mkdir(exist_ok=True)
    shutil.copy(ROOT / "backend/README.md", tmp_path / "backend/README.md")
    return tmp_path


def make_minimal_repository(root: Path) -> tuple[PortableRepository, DecisionService]:
    root.mkdir(parents=True, exist_ok=True)
    repository = PortableRepository(root)
    service = DecisionService(root, root.parent / "cache")
    return repository, service


def save_source_evidence(repository: PortableRepository, root: Path, relative_path: str) -> list[dict[str, object]]:
    source = root / relative_path
    source.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for passage in passages(source, root):
        record = {
            "schema_version": "decision/v1", "record_type": "evidence", "id": passage.id,
            "source": source_identity(source, root),
            "location": {
                "heading_path": passage.heading_path,
                "normalized_passage_sha256": passage.passage_sha256,
                "context_before": passage.context_before,
                "context_after": passage.context_after,
                "display_line": passage.display_line,
            },
            "text": passage.text, "state": "current",
        }
        repository.save("evidence", record)
        records.append(record)
    return records


def test_tasks_markdown_is_ignored_by_default_and_can_be_included(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    repository, service = make_minimal_repository(root)
    (root / "docs").mkdir()
    (root / "docs/architecture.md").write_text("# Architecture\n\nKafka is the durable event platform for this service.\n", encoding="utf-8")
    (root / ".tasks").mkdir()
    (root / ".tasks/ledger.md").write_text("# Task\n\nSQS is a competing delivery alternative for this architecture.\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")

    default_scan = service.scan()

    assert [item["path"] for item in default_scan["documents"]] == ["docs/architecture.md"]
    assert not any("SQS" in item["text"] for item in repository.records("evidence"))

    config = load_yaml(root / ".decision/config.yaml")
    config["extraction"]["include"] = [".tasks"]
    (root / ".decision/config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    included_scan = service.scan()

    assert {item["path"] for item in included_scan["documents"]} == {"docs/architecture.md", ".tasks/ledger.md"}
    assert any("SQS" in item["text"] for item in repository.records("evidence"))


def test_portable_config_schema_validates_extraction_include() -> None:
    repository = PortableRepository(ROOT)
    config = {
        "schema_version": "decision/v1",
        "record_type": "config",
        "id": "project",
        "extraction": {"include": [".tasks"]},
        "connections": [],
    }

    repository.validate_config(config)

    config["extraction"]["include"] = ["../outside"]
    with pytest.raises(DomainError):
        repository.validate_config(config)


def test_scan_removes_only_task_grounded_inferred_claim_and_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    repository, service = make_minimal_repository(root)
    (root / "docs/messaging.md").parent.mkdir(parents=True)
    (root / "docs/messaging.md").write_text("# Messaging\n\nWe chose Kafka because durable replay is required.\n", encoding="utf-8")
    (root / ".tasks").mkdir()
    (root / ".tasks/ledger.md").write_text("# Alternatives\n\nSQS remained an alternative considered for simpler operations.\n", encoding="utf-8")
    docs_evidence = save_source_evidence(repository, root, "docs/messaging.md")[0]
    task_evidence = save_source_evidence(repository, root, ".tasks/ledger.md")[0]
    repository.save("claims", {
        "schema_version": "decision/v1", "record_type": "claim", "id": "claim-task-only",
        "subject": "service-orders", "predicate": "mentioned_in", "object": ".tasks/ledger.md",
        "epistemic_state": "inferred", "confidence": 0.8, "evidence": [task_evidence["id"]],
    })
    repository.save("claims", {
        "schema_version": "decision/v1", "record_type": "claim", "id": "claim-mixed",
        "subject": "service-orders", "predicate": "mentioned_in", "object": "docs/messaging.md",
        "epistemic_state": "inferred", "confidence": 0.8, "evidence": [docs_evidence["id"], task_evidence["id"]],
    })
    repository.save("decisions", {
        "schema_version": "decision/v1", "record_type": "decision", "id": "decision-inferred-messaging",
        "title": "Messaging", "status": "decided", "epistemic_state": "inferred", "selected_option": "option-kafka",
        "evidence": [docs_evidence["id"]], "options": [
            {"id": "option-kafka", "title": "Kafka", "rationale": "Supports durable replay.", "evidence": [docs_evidence["id"]], "delta": {"base": "architecture", "operations": []}},
            {"id": "option-sqs", "title": "SQS", "rationale": "Simpler operations.", "evidence": [task_evidence["id"]], "delta": {"base": "architecture", "operations": []}},
        ],
    })
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")

    service.scan()

    claims = {record["id"]: record for record in repository.records("claims")}
    decision = next(record for record in repository.records("decisions") if record["id"] == "decision-inferred-messaging")
    evidence = {record["id"]: record for record in repository.records("evidence")}
    assert "claim-task-only" not in claims
    assert "claim-mixed" in claims
    assert [option["id"] for option in decision["options"]] == ["option-kafka"]
    assert decision["selected_option"] == "option-kafka"
    assert evidence[task_evidence["id"]]["state"] == "unresolved"
    assert evidence[docs_evidence["id"]]["state"] == "current"


def test_scan_filters_excluded_evidence_from_mixed_inferred_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    repository, service = make_minimal_repository(root)
    docs_path = root / "docs/messaging.md"
    docs_path.parent.mkdir(parents=True)
    docs_path.write_text("# Messaging\n\nThe Kafka shortname broker is used for durable replay.\n", encoding="utf-8")
    (root / ".tasks").mkdir()
    (root / ".tasks/ledger.md").write_text("# Internal\n\nTask-only historical note for this graph.\n", encoding="utf-8")
    docs_evidence = save_source_evidence(repository, root, "docs/messaging.md")[0]
    task_evidence = save_source_evidence(repository, root, ".tasks/ledger.md")[0]
    evidence_ids = [docs_evidence["id"], task_evidence["id"]]
    repository.save("entities", {
        "schema_version": "decision/v1", "record_type": "entity", "id": "entity-mixed-support",
        "kind": "technology", "name": "Kafka", "epistemic_state": "inferred", "confidence": 0.8,
        "evidence": evidence_ids,
    })
    repository.save("entities", {
        "schema_version": "decision/v1", "record_type": "entity", "id": "entity-human-task-support",
        "kind": "technology", "name": "Human-reviewed technology", "epistemic_state": "confirmed",
        "evidence": [task_evidence["id"]],
    })
    repository.save("aliases", {
        "schema_version": "decision/v1", "record_type": "alias", "id": "alias-mixed-support",
        "entity_id": "entity-mixed-support", "name": "Kafka wire", "epistemic_state": "inferred",
        "confidence": 0.8, "evidence": evidence_ids,
    })
    repository.save("aliases", {
        "schema_version": "decision/v1", "record_type": "alias", "id": "alias-task-only",
        "entity_id": "entity-mixed-support", "name": "task-only nickname", "epistemic_state": "inferred",
        "confidence": 0.8, "evidence": [task_evidence["id"]],
    })
    repository.save("claims", {
        "schema_version": "decision/v1", "record_type": "claim", "id": "claim-mixed-support",
        "subject": "entity-mixed-support", "predicate": "mentioned_in", "object": "docs/messaging.md",
        "epistemic_state": "inferred", "confidence": 0.8, "evidence": evidence_ids,
    })
    repository.save("relationships", {
        "schema_version": "decision/v1", "record_type": "relationship", "id": "relationship-mixed-support",
        "from": "entity-mixed-support", "to": "entity-mixed-support", "kind": "related",
        "epistemic_state": "inferred", "confidence": 0.8, "evidence": evidence_ids,
    })
    repository.save("decisions", {
        "schema_version": "decision/v1", "record_type": "decision", "id": "decision-mixed-support",
        "title": "Messaging", "status": "decided", "epistemic_state": "inferred", "selected_option": "option-mixed",
        "evidence": evidence_ids, "options": [
            {"id": "option-mixed", "title": "Kafka", "evidence": evidence_ids, "delta": {"base": "architecture", "operations": [{"op": "add_entity", "entity": {"id": "entity-referenced-current", "kind": "technology", "name": "Referenced Kafka"}}]}},
            {"id": "option-task-only", "title": "Historical", "evidence": [task_evidence["id"]], "delta": {"base": "architecture", "operations": []}},
        ],
    })
    repository.save("entities", {
        "schema_version": "decision/v1", "record_type": "entity", "id": "entity-referenced-current",
        "kind": "technology", "name": "Referenced Kafka", "epistemic_state": "inferred", "confidence": 0.8,
        "evidence": [task_evidence["id"]],
    })
    repository.save("aliases", {
        "schema_version": "decision/v1", "record_type": "alias", "id": "alias-referenced-current",
        "entity_id": "entity-referenced-current", "name": "current broker", "epistemic_state": "inferred",
        "confidence": 0.8, "evidence": [docs_evidence["id"]],
    })
    repository.save("claims", {
        "schema_version": "decision/v1", "record_type": "claim", "id": "claim-referenced-current",
        "subject": "entity-referenced-current", "predicate": "mentioned_in", "object": "docs/messaging.md",
        "epistemic_state": "inferred", "confidence": 0.8, "evidence": [docs_evidence["id"]],
    })
    repository.save("relationships", {
        "schema_version": "decision/v1", "record_type": "relationship", "id": "relationship-referenced-current",
        "from": "entity-referenced-current", "to": "entity-mixed-support", "kind": "related",
        "epistemic_state": "inferred", "confidence": 0.8, "evidence": [docs_evidence["id"]],
    })
    for kind, record in (
        ("aliases", {"schema_version": "decision/v1", "record_type": "alias", "id": "alias-human-history", "entity_id": "entity-mixed-support", "name": "historic broker", "epistemic_state": "confirmed", "confidence": 1.0, "evidence": evidence_ids}),
        ("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": "claim-human-history", "subject": "entity-mixed-support", "predicate": "describes", "object": "historical record", "epistemic_state": "confirmed", "confidence": 1.0, "evidence": evidence_ids}),
        ("relationships", {"schema_version": "decision/v1", "record_type": "relationship", "id": "relationship-human-history", "from": "entity-mixed-support", "to": "entity-mixed-support", "kind": "reviewed", "epistemic_state": "confirmed", "confidence": 1.0, "evidence": evidence_ids}),
        ("decisions", {"schema_version": "decision/v1", "record_type": "decision", "id": "decision-human-history", "title": "Reviewed", "status": "proposed", "epistemic_state": "confirmed", "evidence": evidence_ids, "options": [{"id": "option-human-history", "title": "Reviewed", "evidence": evidence_ids, "delta": {"base": "architecture", "operations": []}}]}),
    ):
        repository.save(kind, record)
    human_review_paths = [
        root / ".decision" / kind / f"{record['id']}.yaml"
        for kind, record in (
            ("aliases", {"id": "alias-human-history"}),
            ("claims", {"id": "claim-human-history"}),
            ("relationships", {"id": "relationship-human-history"}),
            ("decisions", {"id": "decision-human-history"}),
        )
    ]
    human_review_bytes = {path: path.read_bytes() for path in human_review_paths}
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")

    service.scan()

    records = {kind: {record["id"]: record for record in repository.records(kind)} for kind in ("entities", "aliases", "claims", "relationships", "decisions", "evidence")}
    for kind, record_id in (("entities", "entity-mixed-support"), ("aliases", "alias-mixed-support"), ("claims", "claim-mixed-support"), ("relationships", "relationship-mixed-support")):
        assert records[kind][record_id]["evidence"] == [docs_evidence["id"]]
    assert records["entities"]["entity-human-task-support"]["evidence"] == [task_evidence["id"]]
    assert "alias-task-only" not in records["aliases"]
    assert all(task_evidence["id"] not in alias.get("evidence", []) for alias in records["aliases"].values() if alias.get("epistemic_state") == "inferred")
    decision = records["decisions"]["decision-mixed-support"]
    assert decision["evidence"] == [docs_evidence["id"]]
    assert decision["options"][0]["evidence"] == [docs_evidence["id"]]
    assert [option["id"] for option in decision["options"]] == ["option-mixed"]
    assert records["entities"]["entity-referenced-current"]["evidence"] == [docs_evidence["id"]]
    assert all(path.read_bytes() == content for path, content in human_review_bytes.items())
    assert records["evidence"][task_evidence["id"]]["state"] == "unresolved"


def test_scan_removes_unreferenced_task_only_entity_and_relationship(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    repository, service = make_minimal_repository(root)
    (root / ".tasks").mkdir()
    (root / ".tasks/ledger.md").write_text("# Internal\n\nEvidence for disposable inferred nodes.\n", encoding="utf-8")
    evidence = save_source_evidence(repository, root, ".tasks/ledger.md")[0]
    repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "entity-task-only", "kind": "service", "name": "Task Service", "epistemic_state": "inferred", "confidence": 0.8, "evidence": [evidence["id"]]})
    repository.save("relationships", {"schema_version": "decision/v1", "record_type": "relationship", "id": "relationship-task-only", "from": "entity-task-only", "to": "entity-task-only", "kind": "related", "epistemic_state": "inferred", "confidence": 0.8, "evidence": [evidence["id"]]})
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")

    service.scan()

    assert "entity-task-only" not in {record["id"] for record in repository.records("entities")}
    assert "relationship-task-only" not in {record["id"] for record in repository.records("relationships")}
    assert next(record for record in repository.records("evidence") if record["id"] == evidence["id"])["state"] == "unresolved"


def test_scan_scopes_saved_scenario_options_to_their_decision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    repository, service = make_minimal_repository(root)
    (root / "docs").mkdir()
    (root / "docs/current.md").write_text("# Current\n\nCurrent source supports this option.\n", encoding="utf-8")
    (root / ".tasks").mkdir()
    (root / ".tasks/ledger.md").write_text("# Internal\n\nTask-only relationship and option support.\n", encoding="utf-8")
    current = save_source_evidence(repository, root, "docs/current.md")[0]
    task = save_source_evidence(repository, root, ".tasks/ledger.md")[0]
    for entity_id in ("entity-a", "entity-b"):
        repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": entity_id, "kind": "service", "name": entity_id, "epistemic_state": "asserted"})
    repository.save("relationships", {
        "schema_version": "decision/v1", "record_type": "relationship", "id": "relationship-task-only",
        "from": "entity-a", "to": "entity-b", "kind": "related", "epistemic_state": "inferred",
        "confidence": 0.8, "evidence": [task["id"]],
    })
    repository.save("decisions", {
        "schema_version": "decision/v1", "record_type": "decision", "id": "decision-current",
        "title": "Current option", "status": "proposed", "options": [
            {"id": "option-shared", "evidence": [current["id"]], "delta": {"base": "architecture", "operations": []}},
        ],
    })
    repository.save("decisions", {
        "schema_version": "decision/v1", "record_type": "decision", "id": "decision-task-option",
        "title": "Task-only alternative", "status": "proposed", "epistemic_state": "inferred",
        "evidence": [current["id"]], "options": [
            {"id": "option-shared", "evidence": [task["id"]], "delta": {"base": "architecture", "operations": [
                {"op": "add_relationship", "relationship": {"id": "relationship-task-only", "from": "entity-a", "to": "entity-b", "kind": "related"}},
            ]}},
            {"id": "option-current", "evidence": [current["id"]], "delta": {"base": "architecture", "operations": []}},
        ],
    })
    repository.save("scenarios", {
        "schema_version": "decision/v1", "record_type": "scenario", "id": "scenario-current",
        "selections": {"decision-current": "option-shared"},
    })
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")

    service.scan()

    decisions = {record["id"]: record for record in repository.records("decisions")}
    assert [option["id"] for option in decisions["decision-task-option"]["options"]] == ["option-current"]
    assert "relationship-task-only" not in {record["id"] for record in repository.records("relationships")}


@pytest.mark.parametrize("reference_kind", ["entity", "relationship"])
def test_scan_rolls_back_when_task_only_entity_or_relationship_is_referenced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reference_kind: str) -> None:
    root = tmp_path / "repo"
    repository, service = make_minimal_repository(root)
    (root / "docs").mkdir()
    (root / "docs/current.md").write_text("# Current\n\nCurrent source supports the architecture.\n", encoding="utf-8")
    (root / ".tasks").mkdir()
    (root / ".tasks/ledger.md").write_text("# Internal\n\nHistorical task-only source for a relationship.\n", encoding="utf-8")
    current = save_source_evidence(repository, root, "docs/current.md")[0]
    task = save_source_evidence(repository, root, ".tasks/ledger.md")[0]
    for entity_id in ("entity-a", "entity-b"):
        repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": entity_id, "kind": "service", "name": entity_id, "epistemic_state": "asserted"})
    if reference_kind == "entity":
        repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "entity-task", "kind": "service", "name": "Task Entity", "epistemic_state": "inferred", "confidence": 0.8, "evidence": [task["id"]]})
        repository.save("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": "claim-human-ref", "subject": "entity-task", "predicate": "describes", "object": "current", "epistemic_state": "confirmed", "confidence": 1.0, "evidence": [current["id"]]})
        message = "Cannot safely remove task-only entity"
    else:
        repository.save("relationships", {"schema_version": "decision/v1", "record_type": "relationship", "id": "relationship-task", "from": "entity-a", "to": "entity-b", "kind": "related", "epistemic_state": "inferred", "confidence": 0.8, "evidence": [task["id"]]})
        repository.save("decisions", {"schema_version": "decision/v1", "record_type": "decision", "id": "decision-scenario-ref", "title": "Relationship", "status": "proposed", "options": [{"id": "option-ref", "delta": {"base": "architecture", "operations": [{"op": "add_relationship", "relationship": {"id": "relationship-task", "from": "entity-a", "to": "entity-b", "kind": "related"}}]}}]})
        repository.save("scenarios", {"schema_version": "decision/v1", "record_type": "scenario", "id": "scenario-ref", "selections": {"decision-scenario-ref": "option-ref"}})
        message = "Cannot safely remove task-only relationship"
    before = {path.relative_to(root / ".decision"): path.read_bytes() for path in (root / ".decision").rglob("*") if path.is_file()}
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")

    with pytest.raises(DomainError, match=message):
        service.scan()

    after = {path.relative_to(root / ".decision"): path.read_bytes() for path in (root / ".decision").rglob("*") if path.is_file()}
    assert after == before


@pytest.mark.parametrize("decision_state,selected", [("inferred", True), ("confirmed", False)])
def test_scan_rolls_back_when_task_only_relationship_is_in_selected_or_human_decision_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, decision_state: str, selected: bool,
) -> None:
    root = tmp_path / "repo"
    repository, service = make_minimal_repository(root)
    (root / ".tasks").mkdir()
    (root / ".tasks/ledger.md").write_text("# Internal\n\nHistorical task-only relationship support.\n", encoding="utf-8")
    task = save_source_evidence(repository, root, ".tasks/ledger.md")[0]
    repository.save("relationships", {
        "schema_version": "decision/v1", "record_type": "relationship", "id": "relationship-delta-ref",
        "from": "entity-a", "to": "entity-b", "kind": "related", "epistemic_state": "inferred",
        "confidence": 0.8, "evidence": [task["id"]],
    })
    decision = {
        "schema_version": "decision/v1", "record_type": "decision", "id": f"decision-{decision_state}-delta-ref",
        "title": "Relationship", "status": "decided" if selected else "proposed",
        "epistemic_state": decision_state,
        "options": [{"id": "option-ref", "delta": {"base": "architecture", "operations": [
            {"op": "add_relationship", "relationship": {"id": "relationship-delta-ref", "from": "entity-a", "to": "entity-b", "kind": "related"}},
        ]}}],
    }
    if selected:
        decision["selected_option"] = "option-ref"
    repository.save("decisions", decision)
    before = {path.relative_to(root / ".decision"): path.read_bytes() for path in (root / ".decision").rglob("*") if path.is_file()}
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")

    with pytest.raises(DomainError, match="Cannot safely remove task-only relationship"):
        service.scan()

    after = {path.relative_to(root / ".decision"): path.read_bytes() for path in (root / ".decision").rglob("*") if path.is_file()}
    assert after == before


def test_scan_removes_unselected_task_only_inferred_decision_without_references(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    repository, service = make_minimal_repository(root)
    (root / ".tasks").mkdir()
    (root / ".tasks/ledger.md").write_text("# Internal\n\nThis unsupported decision exists only in task notes.\n", encoding="utf-8")
    task = save_source_evidence(repository, root, ".tasks/ledger.md")[0]
    repository.save("decisions", {
        "schema_version": "decision/v1", "record_type": "decision", "id": "decision-task-only",
        "title": "Task-only choice", "status": "proposed", "epistemic_state": "inferred",
        "evidence": [task["id"]], "options": [{
            "id": "option-task-only", "title": "Task-only", "evidence": [task["id"]],
            "delta": {"base": "architecture", "operations": []},
        }],
    })
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")

    service.scan()

    assert "decision-task-only" not in {record["id"] for record in repository.records("decisions")}
    assert next(record for record in repository.records("evidence") if record["id"] == task["id"])["state"] == "unresolved"


def test_task_only_stale_evidence_is_kept_unresolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    repository, service = make_minimal_repository(root)
    (root / ".tasks").mkdir()
    (root / ".tasks/ledger.md").write_text("# Task\n\nThis task passage is retained as historical evidence.\n", encoding="utf-8")
    old_record = save_source_evidence(repository, root, ".tasks/ledger.md")[0]
    (root / ".tasks/ledger.md").unlink()
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")

    service.scan()

    retained = next(record for record in repository.records("evidence") if record["id"] == old_record["id"])
    assert retained["state"] == "unresolved"
    assert retained["text"] == old_record["text"]


def test_scan_fails_closed_for_selected_task_only_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    repository, service = make_minimal_repository(root)
    (root / "docs").mkdir()
    (root / "docs/messaging.md").write_text("# Messaging\n\nKafka is the supported messaging platform here.\n", encoding="utf-8")
    (root / ".tasks").mkdir()
    (root / ".tasks/ledger.md").write_text("# Alternative\n\nSQS was only noted in this internal task evidence.\n", encoding="utf-8")
    kafka_evidence = save_source_evidence(repository, root, "docs/messaging.md")[0]
    task_evidence = save_source_evidence(repository, root, ".tasks/ledger.md")[0]
    repository.save("decisions", {
        "schema_version": "decision/v1", "record_type": "decision", "id": "decision-fail-closed",
        "title": "Messaging", "status": "decided", "epistemic_state": "inferred", "selected_option": "option-sqs",
        "evidence": [task_evidence["id"]], "options": [
            {"id": "option-kafka", "title": "Kafka", "evidence": [kafka_evidence["id"]], "delta": {"base": "architecture", "operations": []}},
            {"id": "option-sqs", "title": "SQS", "evidence": [task_evidence["id"]], "delta": {"base": "architecture", "operations": []}},
        ],
    })
    before = {path.relative_to(root / ".decision"): path.read_bytes() for path in (root / ".decision").rglob("*") if path.is_file()}
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")

    with pytest.raises(DomainError, match="Cannot safely remove task-only option"):
        service.scan()

    after = {path.relative_to(root / ".decision"): path.read_bytes() for path in (root / ".decision").rglob("*") if path.is_file()}
    assert after == before


def test_scan_preserves_human_claim_review_chain_and_references(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    repository, service = make_minimal_repository(root)
    (root / ".tasks").mkdir()
    (root / ".tasks/ledger.md").write_text("# Task\n\nThis passage produced an inferred claim reviewed by a person.\n", encoding="utf-8")
    evidence = save_source_evidence(repository, root, ".tasks/ledger.md")[0]
    inferred = {
        "schema_version": "decision/v1", "record_type": "claim", "id": "claim-reviewed-root",
        "subject": "orders", "predicate": "mentions", "object": "queue", "epistemic_state": "inferred",
        "confidence": 0.8, "evidence": [evidence["id"]],
    }
    repository.save("claims", inferred)
    confirmed = service.review_claim(inferred["id"], "confirmed")
    rejected = service.review_claim(confirmed["id"], "rejected")
    overridden = service.correct_claim(inferred["id"], "orders", "mentions", "alternate-queue")
    before = {record["id"]: (root / ".decision/claims" / f"{record['id']}.yaml").read_bytes() for record in [inferred, confirmed, rejected, overridden]}
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")

    service.scan()

    after = {record["id"]: (root / ".decision/claims" / f"{record['id']}.yaml").read_bytes() for record in [inferred, confirmed, rejected, overridden]}
    claims = {record["id"]: record for record in repository.records("claims")}
    assert after == before
    assert claims[confirmed["id"]]["reviewed_claim"] == inferred["id"]
    assert claims[rejected["id"]]["supersedes"] == [confirmed["id"]]
    assert claims[overridden["id"]]["supersedes"] == sorted({inferred["id"], confirmed["id"], rejected["id"]})
    assert next(record for record in repository.records("evidence") if record["id"] == evidence["id"])["state"] == "unresolved"


def test_demo_overlay_validates_schema_and_references() -> None:
    repo = PortableRepository(ROOT)
    repo.validate_references()
    for kind in ("entities", "evidence", "aliases", "claims", "relationships", "decisions", "scenarios", "connections", "agents"):
        repo.records(kind)


def test_unknown_portable_version_is_rejected_without_mutating_file(tmp_path: Path) -> None:
    root = fixture_repository(tmp_path)
    repo = PortableRepository(root)
    original = next((root / ".decision/entities").glob("*.yaml"))
    before = original.read_bytes()
    record = repo.records("entities")[0]
    record["schema_version"] = "decision/v2"
    with pytest.raises(DomainError, match="Unsupported schema_version"):
        repo.save("entities", record)
    assert original.read_bytes() == before


def test_proposal_preview_and_manual_apply_share_option_delta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = fixture_repository(tmp_path)
    service = DecisionService(root, tmp_path / "cache")
    service.configure_connection({"id": "test", "provider": "mock", "model": "mock"})
    decision = next(record for record in service.repository.records("decisions") if record["id"] == "decision-messaging-platform")
    option = next(item for item in decision["options"] if item["id"] == "option-sqs")
    proposed = {"base": "architecture", "operations": [{"op": "add_entity", "entity": {"id": "preview-queue", "kind": "queue", "name": "Preview Queue"}}]}
    monkeypatch.setattr("switchplinth.service.propose_delta_with_litellm", lambda *args, **kwargs: {"delta": proposed, "rationale": "A reviewable proposal"})
    result = service.propose_delta(decision["id"], option["id"], "Use a preview queue", "test")
    assert result["delta"] == proposed
    assert "preview-queue" in result["preview"]["added"]
    persisted = service.repository.records("decisions")
    untouched = next(record for record in persisted if record["id"] == decision["id"])
    assert next(item for item in untouched["options"] if item["id"] == option["id"])["delta"] == option["delta"]
    untouched["options"] = [{**item, "delta": proposed} if item["id"] == option["id"] else item for item in untouched["options"]]
    service.repository.validate_candidate("decisions", untouched)
    service.repository.save("decisions", untouched)
    applied = next(record for record in service.repository.records("decisions") if record["id"] == decision["id"])
    assert next(item for item in applied["options"] if item["id"] == option["id"])["delta"] == result["delta"]


def test_mock_extraction_writes_decision_options_and_portable_deltas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    (root / ".decision/schema").mkdir(parents=True)
    shutil.copy(ROOT / ".decision/schema/record-v1.schema.json", root / ".decision/schema/record-v1.schema.json")
    for folder in ("entities", "evidence", "aliases", "claims", "relationships", "decisions", "scenarios", "connections", "agents"):
        (root / ".decision" / folder).mkdir()
    source = root / "docs/messaging.md"
    source.parent.mkdir()
    source.write_text("# Messaging\n\n## Decision\n\nWe chose Apache Kafka because replay matters. The Order Service publishes events to Kafka.\n\n## Alternative: managed queue\n\nAmazon SQS would reduce infrastructure work, but replay needs more code.\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    service = DecisionService(root, tmp_path / "cache")
    scan = service.scan()
    assert scan["candidate_decision_count"] >= 1
    decisions = PortableRepository(root).records("decisions")
    extracted = next(record for record in decisions if record.get("epistemic_state") == "inferred")
    assert len(extracted["options"]) == 2
    assert extracted["selected_option"] == extracted["options"][0]["id"]
    assert all(option["delta"]["operations"] for option in extracted["options"])
    assert all(option["evidence"] for option in extracted["options"])
    graph = service.graph_json()
    assert any(entity["name"] == "Apache Kafka" for entity in graph["entities"])
    assert graph["scenario"]["selections"][extracted["id"]] == extracted["selected_option"]
    kafka = next(entity for entity in graph["entities"] if entity["name"] == "Apache Kafka")
    detail = service.entity_detail(kafka["id"])
    assert detail["decisions"]
    assert detail["evidence"]
    sqs = next(option for option in extracted["options"] if option["id"] != extracted["selected_option"])
    scenario_entities = service.graph_json({extracted["id"]: sqs["id"]})["entities"]
    sqs_entity = next(entity for entity in scenario_entities if entity["name"] == "Amazon SQS")
    sqs_detail = service.entity_detail(sqs_entity["id"], {extracted["id"]: sqs["id"]})
    assert sqs_detail["decisions"][0]["selected_option"]["id"] == sqs["id"]
    monkeypatch.setattr("switchplinth.service.qdrant_search", lambda *args, **kwargs: [])
    kafka_answer = service.search("Why Kafka?")
    sqs_answer = service.search("Why SQS?", {extracted["id"]: sqs["id"]})
    inactive_kafka_answer = service.search("Why Kafka?", {extracted["id"]: sqs["id"]})
    assert "Apache Kafka was selected" in kafka_answer["answer"]
    assert "Amazon SQS was selected" in sqs_answer["answer"]
    assert kafka_answer["evidence"][0]["id"] != sqs_answer["evidence"][0]["id"]
    assert "not present in the selected scenario" in inactive_kafka_answer["answer"]
    assert inactive_kafka_answer["scenario_context"]["evidence_context"] == "historical_decision_option"
    assert all(item["context"] == "decision_option" for item in inactive_kafka_answer["evidence"])
    inactive_evidence_ids = {item["id"] for item in inactive_kafka_answer["evidence"]}
    # A claim citing a returned passage, or the unselected Kafka option's own returned evidence, grounds the answer.
    kafka_option = next(option for option in extracted["options"] if option["id"] == extracted["selected_option"])
    kafka_option_evidence_ids = set(kafka_option["evidence"] or extracted["evidence"])
    assert inactive_kafka_answer["grounded"] is bool(inactive_kafka_answer["claims"] or kafka_option_evidence_ids & inactive_evidence_ids)
    assert all(set(claim["evidence"]) & inactive_evidence_ids for claim in inactive_kafka_answer["claims"])


def test_option_entity_legacy_base_duplicate_is_not_compiled_as_conflict(tmp_path: Path) -> None:
    root = fixture_repository(tmp_path)
    service = DecisionService(root, tmp_path / "cache")
    decision = next(record for record in service.repository.records("decisions") if record["id"] == "decision-messaging-platform")
    option = next(option for option in decision["options"] if option["id"] == "option-kafka")
    kafka = next(operation["entity"] for operation in option["delta"]["operations"] if operation["op"] == "add_entity")

    # Older extracted overlays wrote a duplicate base entity without state.
    legacy_entity = {"schema_version": "decision/v1", "record_type": "entity", **kafka}
    service.repository.save("entities", legacy_entity)
    rendered = service.graph_json({decision["id"]: option["id"]})
    assert any(entity["id"] == kafka["id"] for entity in rendered["entities"])
    assert not any(kafka["id"] in conflict for conflict in rendered["scenario"]["conflicts"])
    # An explicit human assertion is real base ownership, so expose the
    # conflict rather than hiding the asserted entity to satisfy the option.
    service.repository.save("entities", {**legacy_entity, "epistemic_state": "asserted"})
    asserted_render = service.graph_json({decision["id"]: option["id"]})
    assert any("Precondition failed" in conflict and kafka["id"] in conflict for conflict in asserted_render["scenario"]["conflicts"])


def test_why_search_requires_full_multiword_entity_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = fixture_repository(tmp_path)
    monkeypatch.setattr("switchplinth.service.qdrant_search", lambda *args, **kwargs: [])
    service = DecisionService(root, tmp_path / "cache")

    partial_match = service.search("Why Order Dead Letter Queue?")
    full_match = service.search("Why Order Service?")

    partial_names = {item["name"] for item in partial_match["scenario_context"]["inactive_entities"]}
    full_inactive_names = {
        item["name"] for item in full_match.get("scenario_context", {}).get("inactive_entities", [])
    }
    assert "Order Dead Letter Queue" in partial_names
    assert "Order Service" not in partial_names
    assert "service-order" in full_match["entities"]
    assert "Order Dead Letter Queue" not in full_inactive_names


def test_scan_relocates_edited_passage_and_retains_evidence_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    (root / ".decision/schema").mkdir(parents=True)
    shutil.copy(ROOT / ".decision/schema/record-v1.schema.json", root / ".decision/schema/record-v1.schema.json")
    for folder in ("entities", "evidence", "aliases", "claims", "relationships", "decisions", "scenarios", "connections", "agents"):
        (root / ".decision" / folder).mkdir()
    source = root / "docs/notes.md"
    source.parent.mkdir()
    source.write_text("# Notes\n\nThis passage records a durable platform constraint for the service.\n\nA stable neighboring passage remains unchanged for relocation context.\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    service = DecisionService(root, tmp_path / "cache")
    service.scan()
    before = next(record for record in service.repository.records("evidence") if "durable platform" in record["text"])
    source.write_text("# Notes\n\nThis passage records a revised durable platform constraint for the service.\n\nA stable neighboring passage remains unchanged for relocation context.\n", encoding="utf-8")
    service.scan()
    after = next(record for record in service.repository.records("evidence") if "revised durable platform" in record["text"])
    assert after["id"] == before["id"]
    assert after["source"]["content_sha256"] != before["source"]["content_sha256"]


def test_scan_preserves_git_blob_when_unavailable_for_unchanged_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    root = tmp_path / "repo"
    repository, service = make_minimal_repository(root)
    source = root / "docs/notes.md"
    source.parent.mkdir()
    source.write_text("# Notes\n\nA stable paragraph records the transaction ordering invariant for this example.\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")

    def recorded_identity(path: Path, repo_root: Path, blob: str | None) -> dict[str, str | None]:
        content = path.read_bytes()
        return {"path": path.relative_to(repo_root).as_posix(), "git_blob": blob, "content_sha256": hashlib.sha256(content).hexdigest()}

    monkeypatch.setattr("switchplinth.service.source_identity", lambda path, repo_root: recorded_identity(path, repo_root, "a" * 40))
    service.scan()
    before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in (root / ".decision").rglob("*")
        if path.is_file()
    }
    markdown_before = source.read_bytes()
    prior = repository.records("evidence")[0]
    assert prior["source"]["git_blob"] == "a" * 40

    monkeypatch.setattr("switchplinth.service.source_identity", source_identity)

    def git_unavailable(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git executable is unavailable")

    monkeypatch.setattr("switchplinth.repository.subprocess.run", git_unavailable)
    service.scan()
    after = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in (root / ".decision").rglob("*")
        if path.is_file()
    }
    current = repository.records("evidence")[0]
    assert current["source"]["git_blob"] == "a" * 40
    assert after == before
    assert source.read_bytes() == markdown_before

    source.write_text("# Notes\n\nA revised paragraph records the transaction ordering invariant for this example.\n", encoding="utf-8")
    service.scan()
    changed = next(record for record in repository.records("evidence") if record.get("state", "current") == "current")
    assert changed["source"]["content_sha256"] != current["source"]["content_sha256"]
    assert changed["source"]["git_blob"] is None

    monkeypatch.setattr("switchplinth.repository.subprocess.run", lambda *args, **kwargs: SimpleNamespace(stdout=f"{'b' * 40}\n"))
    service.scan()
    hashed = next(record for record in repository.records("evidence") if record.get("state", "current") == "current")
    assert hashed["source"]["git_blob"] == "b" * 40


def test_scan_route_rebuilds_after_sqlite_namespace_deletion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from switchplinth.api import create_app

    root = tmp_path / "repo"
    _, service = make_minimal_repository(root)
    source = root / "docs/notes.md"
    source.parent.mkdir()
    source.write_text("# Notes\n\nKafka carries durable events for the transaction service.\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    app = create_app(service)
    app.state.workspace_root = tmp_path.resolve()
    app.state.cache_root = tmp_path / "cache"
    scan_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/discovery/scan")
    open_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/project/open")

    opened = open_route.endpoint(type("Request", (), {"path": "repo"})())
    assert opened["project"]["root"] == str(root.resolve())
    scan_route.endpoint()
    namespace = app.state.service.cache
    index_path = app.state.service.index.path
    assert index_path.is_file()

    shutil.rmtree(namespace)
    scan_route.endpoint()
    assert index_path.is_file()
    assert app.state.service.index.search("Kafka")

    shutil.rmtree(namespace)
    open_route.endpoint(type("Request", (), {"path": "repo"})())
    scan_route.endpoint()

    assert index_path.is_file()
    assert app.state.service.index.search("Kafka")


def test_provider_extraction_uses_relocated_evidence_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    (root / ".decision/schema").mkdir(parents=True)
    shutil.copy(ROOT / ".decision/schema/record-v1.schema.json", root / ".decision/schema/record-v1.schema.json")
    for folder in ("entities", "evidence", "aliases", "claims", "relationships", "decisions", "scenarios", "connections", "agents"):
        (root / ".decision" / folder).mkdir()
    source = root / "docs/notes.md"
    source.parent.mkdir()
    source.write_text("# Notes\n\nWe chose durable queue handling because ordered retries are required.\n\nA stable neighboring paragraph supports evidence relocation across edits.\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    service = DecisionService(root, tmp_path / "cache")
    service.scan()
    prior = next(record for record in service.repository.records("evidence") if "ordered retries" in record["text"])
    source.write_text("# Notes\n\nWe chose durable queue handling because ordered retries and replay are required.\n\nA stable neighboring paragraph supports evidence relocation across edits.\n", encoding="utf-8")
    quote = "We chose durable queue handling because ordered retries and replay are required."
    monkeypatch.setattr("switchplinth.service.extract_with_litellm", lambda connection, text: {
        "entities": [{"name": "Durable Queue", "kind": "queue", "evidence_quote": quote}],
        "decisions": [{"title": "Queue handling", "evidence_quote": quote, "options": [{"title": "Durable queue", "selected": True, "evidence_quote": quote, "delta": {"base": "architecture", "operations": []}}]}],
    })
    service.configure_connection({"id": "test", "provider": "mock", "model": "mock"})
    result = service.extract_with_provider("test")
    current = {record["id"] for record in service.repository.records("evidence")}
    assert result["decisions"]
    assert prior["id"] in current
    assert all(set(record.get("evidence", [])) <= current for record in result["entities"] + result["claims"] + result["decisions"])
    assert result["decisions"][0]["evidence"] == [prior["id"]]


def test_provider_extraction_retries_invalid_delta_and_preserves_rejected_delta_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    (root / ".decision/schema").mkdir(parents=True)
    shutil.copy(ROOT / ".decision/schema/record-v1.schema.json", root / ".decision/schema/record-v1.schema.json")
    for folder in ("entities", "evidence", "aliases", "claims", "relationships", "decisions", "scenarios", "connections", "agents"):
        (root / ".decision" / folder).mkdir()
    source = root / "docs/fulfillment.md"
    source.parent.mkdir()
    quote = "We selected Amazon SQS over Apache Kafka because managed retries reduce operational work."
    source.write_text(f"# Fulfillment transport\n\n{quote}\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    service = DecisionService(root, tmp_path / "cache")
    service.configure_connection({"id": "test", "provider": "mock", "model": "mock-model"})
    base = {"entities": [], "relationships": [], "consequences": [], "decisions": [{"title": "Fulfillment transport", "context": "Choose a transport", "evidence_quote": quote, "options": [
        {"title": "Apache Kafka", "selected": False, "evidence_quote": quote, "delta": {"base": "architecture", "operations": [{"op": "select_kafka_as_transport"}]}},
        {"title": "Amazon SQS", "selected": True, "evidence_quote": quote, "delta": {"base": "architecture", "operations": []}},
    ]}]}
    fixed = {**base, "decisions": [{**base["decisions"][0], "options": [
        {"title": "Apache Kafka", "selected": False, "evidence_quote": quote, "delta": {"base": "architecture", "operations": []}},
        base["decisions"][0]["options"][1],
    ]}]}
    responses = [base, fixed]
    prompts: list[str] = []

    def extract(_connection: dict[str, object], prompt: str) -> dict[str, object]:
        prompts.append(prompt)
        return responses.pop(0)

    monkeypatch.setattr("switchplinth.service.extract_with_litellm", extract)
    result = service.extract_with_provider("test")
    assert len(prompts) == 2
    assert "CORRECTION REQUIRED" in prompts[1]
    assert result["decision_count"] == 1
    decision = result["decisions"][0]
    assert decision["selected_option"] == stable_id("option", "docs/fulfillment.md/Fulfillment transport/Amazon SQS")
    evidence_id = decision["evidence"][0]
    assert service.repository.records("evidence")
    assert next(row for row in service.repository.records("evidence") if row["id"] == evidence_id)["text"] == quote
    first_ids = {kind: {row["id"] for row in service.repository.records(kind)} for kind in ("entities", "aliases", "claims", "decisions")}

    invalid_candidate = {**base, "decisions": [{**base["decisions"][0], "title": "Rejected malformed transport", "options": [
        {**base["decisions"][0]["options"][0], "title": "Queue rejection A"},
        {**base["decisions"][0]["options"][1], "title": "Queue rejection B"},
    ]}]}
    bad_responses = [invalid_candidate, invalid_candidate]
    monkeypatch.setattr("switchplinth.service.extract_with_litellm", lambda *_args: bad_responses.pop(0))
    recovered = service.extract_with_provider("test")
    assert recovered["decision_count"] == 1
    recovered_decision = recovered["decisions"][0]
    assert recovered_decision["extraction_review"]["status"] == "required"
    assert recovered_decision["extraction_review"]["attempts"] == 2
    rejected_option = recovered_decision["extraction_review"]["rejected_options"][0]
    assert rejected_option["delta"] == {"base": "architecture", "operations": [{"op": "select_kafka_as_transport"}]}
    assert "unsupported delta operation" in rejected_option["errors"][0].lower()
    assert all(option["delta"] == {"base": "architecture", "operations": []} for option in recovered_decision["options"])
    assert any("saved with empty active deltas" in item for item in recovered["diagnostics"])
    assert {kind: {row["id"] for row in service.repository.records(kind)} for kind in first_ids}["entities"] == first_ids["entities"]

    malformed_delta = {"decisions": [{"title": "Bad delta", "options": [{"title": "Kafka", "delta": {"base": "architecture"}}]}]}
    assert any("delta must contain only" in item for item in service._invalid_extraction_deltas(malformed_delta))
    expected_entity = {"op": "add_entity", "entity": {"id": "new-service", "kind": "service", "name": "New Service"}, "expect": {"exists": False}}
    valid_expect_response = {"decisions": [{"title": "Expected add", "options": [{"title": "New Service", "delta": {"base": "architecture", "operations": [expected_entity]}}]}]}
    assert service._invalid_extraction_deltas(valid_expect_response) == []
    empty_expect_response = {"decisions": [{"title": "Empty precondition", "options": [{"title": "New Service", "delta": {"base": "architecture", "operations": [{**expected_entity, "expect": {}}]}}]}]}
    assert service._invalid_extraction_deltas(empty_expect_response) == []
    malformed_expect = {**expected_entity, "expect": {"exists": "false"}}
    malformed_expect_response = {"decisions": [{"title": "Malformed precondition", "options": [{"title": "New Service", "delta": {"base": "architecture", "operations": [malformed_expect]}}]}]}
    assert any("malformed" in item and "expect precondition" in item for item in service._invalid_extraction_deltas(malformed_expect_response))
    extra_expect = {**expected_entity, "expect": {"exists": False, "version": 1}}
    extra_expect_response = {"decisions": [{"title": "Extra precondition field", "options": [{"title": "New Service", "delta": {"base": "architecture", "operations": [extra_expect]}}]}]}
    assert any("malformed" in item and "expect precondition" in item for item in service._invalid_extraction_deltas(extra_expect_response))
    missing_operations = {**base, "decisions": [{**base["decisions"][0], "title": "Missing operations retry", "options": [
        {"title": "Kafka", "selected": False, "evidence_quote": quote, "delta": {"base": "architecture"}},
        {"title": "SQS", "selected": True, "evidence_quote": quote, "delta": {"base": "architecture", "operations": []}},
    ]}]}
    corrected_missing_operations = {**missing_operations, "decisions": [{**missing_operations["decisions"][0], "options": [
        {"title": "Kafka", "selected": False, "evidence_quote": quote, "delta": {"base": "architecture", "operations": []}},
        missing_operations["decisions"][0]["options"][1],
    ]}]}
    missing_ops_responses = [missing_operations, corrected_missing_operations]
    missing_ops_prompts: list[str] = []

    def retry_missing_operations(_connection: dict[str, object], prompt: str) -> dict[str, object]:
        missing_ops_prompts.append(prompt)
        return missing_ops_responses.pop(0)

    monkeypatch.setattr("switchplinth.service.extract_with_litellm", retry_missing_operations)
    missing_ops_result = service.extract_with_provider("test")
    assert len(missing_ops_prompts) == 2 and "selected flags" in missing_ops_prompts[1]
    assert missing_ops_result["decision_count"] == 1
    malformed_selection = {"entities": [], "relationships": [], "consequences": [], "decisions": [{
        "title": "Malformed selection", "evidence_quote": quote, "options": [
            {"title": "Kafka", "selected": "false", "evidence_quote": quote, "delta": {"base": "architecture", "operations": []}},
            {"title": "SQS", "selected": True, "evidence_quote": quote, "delta": {"base": "architecture", "operations": []}},
        ],
    }]}
    monkeypatch.setattr("switchplinth.service.extract_with_litellm", lambda *_args: malformed_selection)
    rejected_selection = service.extract_with_provider("test")
    assert rejected_selection["decision_count"] == 0
    assert any("selected values must be booleans" in item for item in rejected_selection["diagnostics"])
    multiple_selected = {**malformed_selection, "decisions": [{**malformed_selection["decisions"][0], "title": "Ambiguous selection", "options": [
        {"title": "Kafka", "selected": True, "evidence_quote": quote, "delta": {"base": "architecture", "operations": []}},
        {"title": "SQS", "selected": True, "evidence_quote": quote, "delta": {"base": "architecture", "operations": []}},
    ]}]}
    monkeypatch.setattr("switchplinth.service.extract_with_litellm", lambda *_args: multiple_selected)
    rejected_multiple = service.extract_with_provider("test")
    assert rejected_multiple["decision_count"] == 0
    assert any("multiple options were marked selected" in item for item in rejected_multiple["diagnostics"])


def test_legacy_overlay_validates_extraction_review_with_bundled_schema(tmp_path: Path) -> None:
    root = tmp_path / "legacy-repo"
    root.mkdir()
    repository = PortableRepository(root)
    schema_path = root / ".decision/schema/record-v1.schema.json"
    legacy_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    legacy_schema["properties"].pop("extraction_review", None)
    legacy_schema["$defs"].pop("extraction_review", None)
    schema_path.write_text(json.dumps(legacy_schema), encoding="utf-8")
    legacy_schema_bytes = schema_path.read_bytes()

    old_decision = {
        "schema_version": "decision/v1", "record_type": "decision", "id": "legacy-decision",
        "title": "Legacy decision", "status": "proposed", "options": [
            {"id": "legacy-option", "title": "Legacy option", "delta": {"base": "architecture", "operations": []}},
        ],
    }
    repository.save("decisions", old_decision)
    assert repository.records("decisions") == [old_decision]

    malformed = {**old_decision, "extraction_review": {"status": "resolved", "attempts": 0, "rejected_options": []}}
    with pytest.raises(DomainError, match="Invalid extraction_review"):
        repository.validate_candidate("decisions", malformed)
    with pytest.raises(DomainError, match="Invalid extraction_review"):
        repository.save("decisions", malformed)

    malformed_path = root / ".decision/decisions/legacy-decision.yaml"
    malformed_path.write_text(yaml.safe_dump(malformed, sort_keys=False), encoding="utf-8")
    with pytest.raises(DomainError, match="Invalid extraction_review"):
        repository.records("decisions")
    with pytest.raises(DomainError, match="Invalid extraction_review"):
        repository.records_unchecked("decisions")
    assert schema_path.read_bytes() == legacy_schema_bytes


def test_invalid_relationship_deltas_are_quarantined_and_manually_resolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from switchplinth.api import DeltaRequest, create_app

    root = tmp_path / "repo"
    (root / ".decision/schema").mkdir(parents=True)
    shutil.copy(ROOT / "backend/src/switchplinth/record-v1.schema.json", root / ".decision/schema/record-v1.schema.json")
    for folder in ("entities", "evidence", "aliases", "claims", "relationships", "decisions", "scenarios", "connections", "agents"):
        (root / ".decision" / folder).mkdir()
    quote = "We selected SQS for managed retries over Kafka's self-managed queueing."
    (root / "notes.md").write_text(f"# Transport\n\n{quote}\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    service = DecisionService(root, tmp_path / "cache")
    service.configure_connection({"id": "test", "provider": "mock", "model": "mock-model"})
    deltas = [
        {"base": "architecture", "operations": [{"op": "add_relationship", "relationship": {"id": "missing-kafka-edge", "from": "missing-a", "to": "missing-b", "kind": "uses"}}]},
        {"base": "architecture", "operations": [{"op": "add_relationship", "relationship": {"id": "missing-sqs-edge", "from": "missing-c", "to": "missing-d", "kind": "uses"}}]},
    ]
    response = {"entities": [], "relationships": [], "consequences": [], "decisions": [{
        "title": "Transport decision", "evidence_quote": quote, "options": [
            {"title": "Kafka", "selected": False, "evidence_quote": quote, "delta": deltas[0]},
            {"title": "SQS", "selected": True, "evidence_quote": quote, "delta": deltas[1]},
        ],
    }]}
    monkeypatch.setattr("switchplinth.service.extract_with_litellm", lambda *_args: response)
    extracted = service.extract_with_provider("test")
    assert extracted["decision_count"] == 1, extracted["diagnostics"]
    decision = extracted["decisions"][0]
    review = decision["extraction_review"]
    assert review["status"] == "required" and review["attempts"] == 1
    assert [item["delta"] for item in review["rejected_options"]] == deltas
    assert all("references an unknown entity" in item["errors"][0] for item in review["rejected_options"])
    assert all(option["delta"] == {"base": "architecture", "operations": []} for option in decision["options"])
    stored = next(item for item in service.repository.records("decisions") if item["id"] == decision["id"])
    assert stored["extraction_review"] == review
    malformed = {**stored, "extraction_review": {**review, "status": "resolved"}}
    with pytest.raises(DomainError):
        service.repository.validate_candidate("decisions", malformed)

    # Review metadata is exposed after reload, while its rejected operations
    # remain outside the compiled graph and active option deltas.
    graph_decision = next(item for item in service.graph_json()["decisions"] if item["id"] == decision["id"])
    assert graph_decision["extraction_review"] == review
    assert all(option["delta"]["operations"] == [] for option in graph_decision["options"])
    assert not service.graph_json()["relationships"]

    app = create_app(service)
    decisions_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/decisions")
    option_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/decisions/{decision_id}/options/{option_id}")
    api_decision = next(item for item in decisions_route.endpoint() if item["id"] == decision["id"])
    assert api_decision["extraction_review"] == review
    first, second = review["rejected_options"]
    partial = option_route.endpoint(decision["id"], first["option_id"], DeltaRequest(delta={"base": "architecture", "operations": []}))
    assert len(partial["extraction_review"]["rejected_options"]) == 1
    assert partial["extraction_review"]["rejected_options"][0]["option_id"] == second["option_id"]
    final = option_route.endpoint(decision["id"], second["option_id"], DeltaRequest(delta={"base": "architecture", "operations": []}))
    assert final["extraction_review"] is None
    resolved = next(item for item in service.repository.records("decisions") if item["id"] == decision["id"])
    assert "extraction_review" not in resolved
    assert resolved["evidence"] == decision["evidence"] and resolved["inferred_by"] == decision["inferred_by"]


def test_empty_delta_fallback_does_not_hide_unrelated_decision_validation_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    (root / ".decision/schema").mkdir(parents=True)
    shutil.copy(ROOT / "backend/src/switchplinth/record-v1.schema.json", root / ".decision/schema/record-v1.schema.json")
    for folder in ("entities", "evidence", "aliases", "claims", "relationships", "decisions", "scenarios", "connections", "agents"):
        (root / ".decision" / folder).mkdir()
    quote = "The team selected SQS for managed retries over Kafka."
    (root / "notes.md").write_text(f"# Transport\n\n{quote}\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    service = DecisionService(root, tmp_path / "cache")
    service.configure_connection({"id": "test", "provider": "mock", "model": "mock-model"})
    response = {"entities": [], "relationships": [], "consequences": [], "decisions": [{
        "title": "Transport decision", "evidence_quote": quote, "options": [
            {"title": "SQS", "selected": True, "evidence_quote": quote, "delta": {"base": "architecture", "operations": [{"op": "add_relationship", "relationship": {"id": "bad-edge", "from": "missing-a", "to": "missing-b", "kind": "uses"}}]}},
        ],
    }]}
    monkeypatch.setattr("switchplinth.service.extract_with_litellm", lambda *_args: response)
    validate = service.repository.validate_candidate
    attempts: list[dict[str, object]] = []

    def fail_decision(kind: str, candidate: dict[str, object]) -> None:
        if kind == "decisions":
            attempts.append(candidate)
            raise DomainError("unrelated decision invariant")
        validate(kind, candidate)

    monkeypatch.setattr(service.repository, "validate_candidate", fail_decision)
    result = service.extract_with_provider("test")
    assert result["decision_count"] == 0
    assert len(attempts) == 2
    assert attempts[0]["options"][0]["delta"]["operations"]
    assert attempts[1]["options"][0]["delta"]["operations"] == []
    assert any("unrelated decision invariant" in item for item in result["diagnostics"])


def test_provider_extraction_deduplicates_only_unambiguous_inferred_choice_sets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    (root / ".decision/schema").mkdir(parents=True)
    shutil.copy(ROOT / ".decision/schema/record-v1.schema.json", root / ".decision/schema/record-v1.schema.json")
    for folder in ("entities", "evidence", "aliases", "claims", "relationships", "decisions", "scenarios", "connections", "agents"):
        (root / ".decision" / folder).mkdir()
    quote = "The team selected SQS for managed retries and Kafka for ordered event replay."
    (root / "notes.md").write_text(f"# Messaging\n\n{quote}\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    service = DecisionService(root, tmp_path / "cache")
    service.configure_connection({"id": "test", "provider": "mock", "model": "mock-model"})

    def decision(title: str, option_a: str, option_b: str, selected: str) -> dict[str, object]:
        return {"title": title, "context": "Select a messaging approach", "evidence_quote": quote, "options": [
            {"title": option_a, "selected": selected == option_a, "evidence_quote": quote, "delta": {"base": "architecture", "operations": []}},
            {"title": option_b, "selected": selected == option_b, "evidence_quote": quote, "delta": {"base": "architecture", "operations": []}},
        ]}

    first_response = {"entities": [], "relationships": [], "consequences": [], "decisions": [
        decision("Transport choice", "Amazon SQS", "Apache Kafka", "Amazon SQS"),
        decision("Replay choice", "Replay with Apache Kafka", "Replay with Amazon SQS", "Replay with Apache Kafka"),
    ]}
    monkeypatch.setattr("switchplinth.service.extract_with_litellm", lambda *_args: first_response)
    first = service.extract_with_provider("test")
    assert first["decision_count"] == 2, first["diagnostics"]
    initial_records = service.repository.records("decisions")
    initial_ids = {record["id"] for record in initial_records}
    assert len(initial_ids) == 2

    drifted = {"entities": [], "relationships": [], "consequences": [], "decisions": [
        decision("Transport evaluation and selection", "Use Amazon SQS", "Use Apache Kafka", "Use Amazon SQS"),
    ]}
    monkeypatch.setattr("switchplinth.service.extract_with_litellm", lambda *_args: drifted)
    repeated = service.extract_with_provider("test")
    assert repeated["decision_count"] == 0
    assert {record["id"] for record in service.repository.records("decisions")} == initial_ids
    assert next(record for record in service.repository.records("decisions") if record["title"] == "Transport choice")["title"] == "Transport choice"

    original = next(record for record in service.repository.records("decisions") if record["title"] == "Transport choice")
    duplicate_id = stable_id("decision", "notes.md/Transport duplicate")
    duplicate_options = [
        {**option, "id": stable_id("option", f"notes.md/Transport duplicate/{option['title']}")}
        for option in original["options"]
    ]
    duplicate = {**original, "id": duplicate_id, "title": "Transport duplicate", "options": duplicate_options}
    duplicate["selected_option"] = next(
        new["id"] for old, new in zip(original["options"], duplicate_options) if old["id"] == original["selected_option"]
    )
    service.repository.save("decisions", duplicate)
    ambiguous = service.extract_with_provider("test")
    assert ambiguous["decision_count"] == 1
    assert any("may duplicate an existing decision" in item and "human review" in item for item in ambiguous["diagnostics"])

    counts = {kind: len(service.repository.records(kind)) for kind in ("entities", "aliases", "claims", "decisions")}
    service.extract_with_provider("test")
    assert {kind: len(service.repository.records(kind)) for kind in counts} == counts


def test_provider_extraction_rebuilds_indexes_from_saved_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    (root / ".decision/schema").mkdir(parents=True)
    shutil.copy(ROOT / ".decision/schema/record-v1.schema.json", root / ".decision/schema/record-v1.schema.json")
    for folder in ("entities", "evidence", "aliases", "claims", "relationships", "decisions", "scenarios", "connections", "agents"):
        (root / ".decision" / folder).mkdir()
    source = root / "notes.md"
    quote = "Fresh Queue carries invoice retries while Human Ledger stores accepted payments."
    source.write_text(f"# Payment flow\n\n{quote}\n", encoding="utf-8")
    indexed_graphs: list[set[str]] = []

    def record_qdrant_rebuild(_url: str, _evidence: list[object], graph: Graph, _collection: str, **_kwargs: object) -> str:
        indexed_graphs.append(set(graph.entities))
        return "indexed test vectors"

    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", record_qdrant_rebuild)
    monkeypatch.setattr("switchplinth.service.extract_with_litellm", lambda _connection, _text: {
        "entities": [{"name": "Fresh Queue", "kind": "queue", "evidence_quote": quote}],
        "relationships": [], "consequences": [], "decisions": [],
    })
    service = DecisionService(root, tmp_path / "cache")
    service.configure_connection({"id": "selected-model", "provider": "mock", "model": "mock-model"})

    result = service.extract_with_provider("selected-model")

    fresh_queue_id = stable_id("entity", "fresh queue")
    assert result["provider"] == "mock"
    assert result["model"] == "mock-model"
    assert result["entity_count"] == 1
    assert result["index"]["qdrant"] == "indexed test vectors"
    assert len(indexed_graphs) == 2  # The initial scan and post-extraction rebuild.
    assert fresh_queue_id in indexed_graphs[-1]
    indexed_passage = service.index.search("Fresh Queue")
    assert indexed_passage and fresh_queue_id in indexed_passage[0]["metadata"]["entity_ids"]


def test_provider_extraction_does_not_persist_mock_inferences_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    (root / ".decision/schema").mkdir(parents=True)
    shutil.copy(ROOT / ".decision/schema/record-v1.schema.json", root / ".decision/schema/record-v1.schema.json")
    for folder in ("entities", "evidence", "aliases", "claims", "relationships", "decisions", "scenarios", "connections", "agents"):
        (root / ".decision" / folder).mkdir()
    (root / "notes.md").write_text("# Messaging\n\nWe chose Apache Kafka because ordered delivery keeps the event pipeline reliable.\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    service = DecisionService(root, tmp_path / "cache")
    service.configure_connection({"id": "selected-model", "provider": "mock", "model": "mock-model"})
    monkeypatch.setattr("switchplinth.service.extract_with_litellm", lambda *_args: (_ for _ in ()).throw(RuntimeError("provider unavailable")))

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.extract_with_provider("selected-model")

    assert service.repository.records("entities") == []
    assert service.repository.records("aliases") == []
    assert service.repository.records("claims") == []
    assert service.repository.records("decisions") == []
    assert service.repository.records("evidence")


def test_provider_extraction_rolls_back_partial_records_on_invalid_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    (root / ".decision/schema").mkdir(parents=True)
    shutil.copy(ROOT / ".decision/schema/record-v1.schema.json", root / ".decision/schema/record-v1.schema.json")
    for folder in ("entities", "evidence", "aliases", "claims", "relationships", "decisions", "scenarios", "connections", "agents"):
        (root / ".decision" / folder).mkdir()
    quote = "Fresh Queue carries invoice retries while Ledger Store keeps accepted payments."
    (root / "notes.md").write_text(f"# Payment flow\n\n{quote}\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    monkeypatch.setattr("switchplinth.service.extract_with_litellm", lambda *_args: {
        "entities": [
            {"name": "Fresh Queue", "kind": "queue", "evidence_quote": quote},
            {"name": "Ledger Store", "kind": "datastore", "evidence_quote": quote, "confidence": "not-a-number"},
        ],
        "relationships": [], "consequences": [], "decisions": [],
    })
    service = DecisionService(root, tmp_path / "cache")
    service.configure_connection({"id": "selected-model", "provider": "mock", "model": "mock-model"})

    with pytest.raises(ValueError):
        service.extract_with_provider("selected-model")

    assert service.repository.records("entities") == []
    assert service.repository.records("aliases") == []
    assert service.repository.records("claims") == []
    assert service.repository.records("relationships") == []
    assert service.repository.records("decisions") == []
    assert service.repository.records("evidence")


def test_provider_extraction_surfaces_failed_index_reconciliation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    (root / ".decision/schema").mkdir(parents=True)
    shutil.copy(ROOT / ".decision/schema/record-v1.schema.json", root / ".decision/schema/record-v1.schema.json")
    for folder in ("entities", "evidence", "aliases", "claims", "relationships", "decisions", "scenarios", "connections", "agents"):
        (root / ".decision" / folder).mkdir()
    quote = "Fresh Queue carries invoice retries while Ledger Store keeps accepted payments."
    (root / "notes.md").write_text(f"# Payment flow\n\n{quote}\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    monkeypatch.setattr("switchplinth.service.extract_with_litellm", lambda *_args: {
        "entities": [
            {"name": "Fresh Queue", "kind": "queue", "evidence_quote": quote},
            {"name": "Ledger Store", "kind": "datastore", "evidence_quote": quote, "confidence": "not-a-number"},
        ],
        "relationships": [], "consequences": [], "decisions": [],
    })
    service = DecisionService(root, tmp_path / "cache")
    service.configure_connection({"id": "selected-model", "provider": "mock", "model": "mock-model"})
    rebuild_indexes = service._rebuild_indexes
    rebuild_count = 0

    def fail_rollback_rebuild(evidence: list[object]) -> dict[str, object]:
        nonlocal rebuild_count
        rebuild_count += 1
        if rebuild_count == 2:
            raise OSError("reconciliation unavailable")
        return rebuild_indexes(evidence)  # type: ignore[arg-type]

    monkeypatch.setattr(service, "_rebuild_indexes", fail_rollback_rebuild)

    with pytest.raises(RuntimeError, match="indexes could not be reconciled.*reconciliation unavailable"):
        service.extract_with_provider("selected-model")

    assert service.repository.records("entities") == []
    assert service.repository.records("claims") == []


def test_provider_persists_relationship_and_decision_consequence_without_overwriting_edits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    (root / ".decision/schema").mkdir(parents=True)
    shutil.copy(ROOT / ".decision/schema/record-v1.schema.json", root / ".decision/schema/record-v1.schema.json")
    for folder in ("entities", "evidence", "aliases", "claims", "relationships", "decisions", "scenarios", "connections", "agents"):
        (root / ".decision" / folder).mkdir()
    source = root / "docs/arbitrary.md"
    source.parent.mkdir()
    quote = "Acme Relay sends invoices to Ledger Store; this requires a dedicated on-call rotation."
    source.write_text(f"# Notes\n\n{quote}\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    service = DecisionService(root, tmp_path / "cache")
    service.configure_connection({"id": "test", "provider": "mock", "model": "mock"})
    generated_delta = {"base": "architecture", "operations": []}
    response = {
        "entities": [
            {"name": "Acme Relay", "kind": "service", "evidence_quote": quote},
            {"name": "Ledger Store", "kind": "datastore", "evidence_quote": quote},
        ],
        "relationships": [{"from_name": "Acme Relay", "to_name": "Ledger Store", "predicate": "stores_in", "confidence": 0.93, "evidence_quote": quote}],
        "decisions": [{"title": "Invoice delivery", "context": "Choose delivery architecture", "evidence_quote": quote, "options": [{"title": "Relay delivery", "selected": True, "rationale": "Keeps delivery reliable", "evidence_quote": quote, "delta": generated_delta}]}],
        "consequences": [{"decision_title": "Invoice delivery", "predicate": "requires", "object": "a dedicated on-call rotation", "confidence": 0.88, "evidence_quote": quote}],
    }
    monkeypatch.setattr("switchplinth.service.extract_with_litellm", lambda connection, text: response)
    first = service.extract_with_provider("test")
    assert len(first["relationships"]) == 1
    assert first["relationships"][0]["confidence"] == 0.93
    assert len(first["consequences"]) == 1
    decision = first["decisions"][0]
    consequence = first["consequences"][0]
    assert consequence["subject"] == decision["id"]
    assert consequence["evidence"] == decision["evidence"]

    # Provider refresh with a changed model answer is additive; portable edits win.
    edited_delta = {"base": "architecture", "operations": [{"op": "add_entity", "entity": {"id": "human-choice", "kind": "component", "name": "Human choice"}}]}
    decision_path = root / ".decision/decisions" / f"{decision['id']}.yaml"
    record = service.repository.records("decisions")[0]
    record["options"][0]["delta"] = edited_delta
    service.repository.save("decisions", record)
    response["decisions"][0]["options"][0]["delta"] = generated_delta
    second = service.extract_with_provider("test")
    persisted = next(item for item in service.repository.records("decisions") if item["id"] == decision["id"])
    assert persisted["options"][0]["delta"] == edited_delta
    assert second["decisions"] == []
    assert decision_path.exists()


def test_corrected_alias_and_claim_survive_provider_rescan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = fixture_repository(tmp_path)
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    service = DecisionService(root, tmp_path / "cache")
    entities = service.repository.records("entities")
    evidence = service.repository.records("evidence")[0]
    wrong, right = entities[:2]
    original_alias = {"schema_version": "decision/v1", "record_type": "alias", "id": "alias-correction-fixture", "entity_id": wrong["id"], "name": "corrected-service-name", "epistemic_state": "inferred", "confidence": 0.71, "evidence": [evidence["id"]]}
    service.repository.save("aliases", original_alias)
    corrected_alias = service.correct_alias(original_alias["id"], original_alias["name"], right["id"])
    assert corrected_alias["epistemic_state"] == "asserted"
    assert original_alias["id"] in corrected_alias["supersedes"]
    active_aliases = effective_aliases(service.repository.records("aliases"))
    assert not any(alias["id"] == original_alias["id"] for alias in active_aliases)
    assert any(alias["id"] == corrected_alias["id"] and alias["entity_id"] == right["id"] for alias in active_aliases)

    original_claim = {"schema_version": "decision/v1", "record_type": "claim", "id": "claim-correction-fixture", "subject": wrong["id"], "predicate": "uses", "object": right["id"], "epistemic_state": "inferred", "confidence": 0.79, "evidence": [evidence["id"]]}
    service.repository.save("claims", original_claim)
    corrected_claim = service.correct_claim(original_claim["id"], right["id"], "calls", wrong["id"])
    assert original_claim["id"] in corrected_claim["supersedes"]
    active_claims = effective_claims([Claim(record["id"], record["subject"], record["predicate"], record["object"], record["epistemic_state"], record["confidence"], record.get("evidence", []), record.get("source_path"), record.get("supersedes", [])) for record in service.repository.records("claims")])
    assert not any(claim.id == original_claim["id"] for claim in active_claims)
    assert any(claim.id == corrected_claim["id"] and claim.predicate == "calls" for claim in active_claims)

    service.configure_connection({"id": "test", "provider": "mock", "model": "mock"})
    monkeypatch.setattr("switchplinth.service.extract_with_litellm", lambda connection, text: {"entities": [], "relationships": [], "consequences": [], "decisions": []})
    service.extract_with_provider("test")
    assert original_alias["id"] in {record["id"] for record in service.repository.records("aliases")}
    assert corrected_alias["id"] in {record["id"] for record in effective_aliases(service.repository.records("aliases"))}
    rescanned_claims = [Claim(record["id"], record["subject"], record["predicate"], record["object"], record["epistemic_state"], record["confidence"], record.get("evidence", []), record.get("source_path"), record.get("supersedes", [])) for record in service.repository.records("claims")]
    assert any(claim.id == corrected_claim["id"] for claim in effective_claims(rescanned_claims))


def test_correction_routes_accept_changed_fields_and_persist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from switchplinth.api import create_app

    root = fixture_repository(tmp_path)
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    monkeypatch.setattr("switchplinth.service.qdrant_search", lambda *args, **kwargs: [])
    service = DecisionService(root, tmp_path / "cache")
    entities = service.repository.records("entities")
    evidence_id = service.repository.records("evidence")[0]["id"]
    original_alias = {"schema_version": "decision/v1", "record_type": "alias", "id": "alias-api-correction", "entity_id": entities[0]["id"], "name": "route-corrected-name", "epistemic_state": "inferred", "confidence": 0.7, "evidence": [evidence_id]}
    original_claim = {"schema_version": "decision/v1", "record_type": "claim", "id": "claim-api-correction", "subject": entities[0]["id"], "predicate": "uses", "object": entities[1]["id"], "epistemic_state": "inferred", "confidence": 0.7, "evidence": [evidence_id]}
    service.repository.save("aliases", original_alias)
    service.repository.save("claims", original_claim)
    app = create_app(service)
    from switchplinth.api import AliasCorrectionRequest, ClaimCorrectionRequest
    alias_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/aliases/{alias_id}/correct")
    claim_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/claims/{claim_id}/correct")
    alias_response = alias_route.endpoint(original_alias["id"], AliasCorrectionRequest(name=original_alias["name"], entity_id=entities[1]["id"]))
    claim_response = claim_route.endpoint(original_claim["id"], ClaimCorrectionRequest(subject=entities[1]["id"], predicate="calls", object=entities[0]["id"]))
    assert alias_response["entity_id"] == entities[1]["id"]
    assert claim_response["predicate"] == "calls"
    service.scan()
    assert any(alias["id"] != original_alias["id"] and alias["entity_id"] == entities[1]["id"] and alias["name"] == original_alias["name"] for alias in effective_aliases(service.repository.records("aliases")))
    claims = [Claim(row["id"], row["subject"], row["predicate"], row["object"], row["epistemic_state"], row["confidence"], row.get("evidence", []), row.get("source_path"), row.get("supersedes", [])) for row in service.repository.records("claims")]
    assert any(claim.subject == entities[1]["id"] and claim.predicate == "calls" and claim.object == entities[0]["id"] for claim in effective_claims(claims))


def test_claim_correction_can_target_option_entity_and_projects_per_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    (root / ".decision/schema").mkdir(parents=True)
    shutil.copy(ROOT / ".decision/schema/record-v1.schema.json", root / ".decision/schema/record-v1.schema.json")
    for folder in ("entities", "evidence", "aliases", "claims", "relationships", "decisions", "scenarios", "connections", "agents"):
        (root / ".decision" / folder).mkdir()
    source = root / "docs/messaging.md"
    source.parent.mkdir()
    quote = "The Order Service publishes events through Apache Kafka. We chose Apache Kafka because replay matters."
    source.write_text(f"# Messaging\n\n{quote}\n\n## Alternative: managed queue\n\nAmazon SQS would reduce infrastructure work, but replay needs more code.\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    service = DecisionService(root, tmp_path / "cache")
    service.scan()
    decision = service.repository.records("decisions")[0]
    kafka_option = decision["options"][0]
    kafka_id = next(operation["entity"]["id"] for operation in kafka_option["delta"]["operations"] if operation["op"] == "add_entity")
    sqs_option = next(option for option in decision["options"] if option["id"] != kafka_option["id"])
    order_id = next(entity["id"] for entity in service.repository.records("entities") if entity["name"] == "Order Service")
    evidence = next(record for record in service.repository.records("evidence") if quote in record["text"])
    original = {"schema_version": "decision/v1", "record_type": "claim", "id": "claim-option-entity-correction", "subject": order_id, "predicate": "mentioned_in", "object": "docs/messaging.md", "epistemic_state": "inferred", "confidence": 0.8, "evidence": [evidence["id"]]}
    service.repository.save("claims", original)
    from switchplinth.api import ClaimCorrectionRequest, create_app
    app = create_app(service)
    claim_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/claims/{claim_id}/correct")
    correction = claim_route.endpoint(original["id"], ClaimCorrectionRequest(subject=order_id, predicate="uses", object=kafka_id))
    default_graph = service.graph_json()
    assert any(edge["from"] == order_id and edge["to"] == kafka_id and edge["claim_id"] == correction["id"] for edge in default_graph["relationships"])
    alternate_graph = service.graph_json({decision["id"]: sqs_option["id"]})
    assert not any(edge["from"] == order_id and edge["to"] == kafka_id for edge in alternate_graph["relationships"])
    assert any(correction["id"] in issue and kafka_id in issue for issue in alternate_graph["scenario"]["invalid_assumptions"])
    persisted = {record["id"]: record for record in service.repository.records("claims")}
    assert persisted[original["id"]]["epistemic_state"] == "inferred"
    assert persisted[correction["id"]]["epistemic_state"] == "asserted"
    service.configure_connection({"id": "test", "provider": "mock", "model": "mock"})
    provider_result = {"entities": [{"name": "Apache Kafka", "kind": "technology", "evidence_quote": quote}], "relationships": [], "decisions": []}
    monkeypatch.setattr("switchplinth.service.extract_with_litellm", lambda connection, text: provider_result)
    service.extract_with_provider("test")
    rescanned = service.repository.records("claims")
    assert next(record for record in rescanned if record["id"] == original["id"])["epistemic_state"] == "inferred"
    active = effective_claims([Claim(record["id"], record["subject"], record["predicate"], record["object"], record["epistemic_state"], record["confidence"], record.get("evidence", []), record.get("source_path"), record.get("supersedes", [])) for record in rescanned])
    assert any(claim.id == correction["id"] and claim.subject == order_id and claim.object == kafka_id for claim in active)


def test_scenario_delta_removing_claim_derived_base_edge_stays_removed(tmp_path: Path) -> None:
    from switchplinth.domain import stable_id

    root = fixture_repository(tmp_path)
    service = DecisionService(root, tmp_path / "cache")
    base_entities = sorted(service.graph()[0].entities.values(), key=lambda entity: entity.id)
    evidence = service.repository.records("evidence")[0]
    source, target = base_entities[:2]
    relationship_id = stable_id("relationship", f"{source.id}/uses/{target.id}")
    service.repository.save("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": "claim-removable-edge", "subject": source.id, "predicate": "uses", "object": target.id, "epistemic_state": "inferred", "confidence": 0.9, "evidence": [evidence["id"]]})
    assert relationship_id in service.graph()[0].relationships
    decision = {"schema_version": "decision/v1", "record_type": "decision", "id": "decision-remove-claim-edge", "title": "Remove the dependency", "status": "proposed", "selected_option": "option-remove-claim-edge", "options": [{"id": "option-remove-claim-edge", "title": "Remove dependency", "delta": {"base": "architecture", "operations": [{"op": "remove_relationship", "relationship": {"id": relationship_id}}]}}]}
    service.repository.save("decisions", decision)
    rendered = service.graph_json()
    assert not any(edge["id"] == relationship_id for edge in rendered["relationships"])
    assert relationship_id in rendered["scenario"]["affected"]["removed"]


def test_preview_delta_returns_scenario_without_persisting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = fixture_repository(tmp_path)
    service = DecisionService(root, tmp_path / "cache")
    decision = next(record for record in service.repository.records("decisions") if record["id"] == "decision-messaging-platform")
    option = next(item for item in decision["options"] if item["id"] == "option-sqs")
    proposed = {"base": "architecture", "operations": [{"op": "add_entity", "entity": {"id": "unpersisted-preview", "kind": "queue", "name": "Preview Queue"}}]}
    result = service.preview_delta(decision["id"], option["id"], proposed, {decision["id"]: option["id"]})
    assert "unpersisted-preview" in {entity["id"] for entity in result["graph"]["entities"]}
    saved = next(record for record in service.repository.records("decisions") if record["id"] == decision["id"])
    saved_option = next(item for item in saved["options"] if item["id"] == option["id"])
    assert saved_option["delta"] != proposed


def test_preview_delta_rejects_null_operation_without_writing_canonical_files(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from switchplinth.api import create_app

    root = fixture_repository(tmp_path)
    service = DecisionService(root, tmp_path / "cache")
    app = create_app(service)
    canonical_before = {
        path.relative_to(root / ".decision"): path.read_bytes()
        for path in (root / ".decision").rglob("*")
        if path.is_file()
    }
    decision = next(record for record in service.repository.records("decisions") if record["id"] == "decision-messaging-platform")
    option = next(item for item in decision["options"] if item["id"] == "option-sqs")

    response = TestClient(app).post(
        "/api/v1/scenarios/preview-delta",
        json={
            "decision_id": decision["id"],
            "option_id": option["id"],
            "delta": {"base": "architecture", "operations": [None]},
        },
    )

    canonical_after = {
        path.relative_to(root / ".decision"): path.read_bytes()
        for path in (root / ".decision").rglob("*")
        if path.is_file()
    }
    assert response.status_code == 422
    assert canonical_after == canonical_before


def test_scenarios_list_returns_saved_records_sorted(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from switchplinth.api import create_app

    root = fixture_repository(tmp_path)
    service = DecisionService(root, tmp_path / "cache")
    client = TestClient(create_app(service))
    canonical_before = {
        path.relative_to(root / ".decision"): path.read_bytes()
        for path in (root / ".decision").rglob("*")
        if path.is_file()
    }

    initial = client.get("/api/v1/scenarios")
    assert initial.status_code == 200
    initial_records = initial.json()
    current = next(record for record in initial_records if record["id"] == "scenario-current")
    assert current == {
        "id": "scenario-current",
        "name": "Current selected architecture",
        "selections": {"decision-messaging-platform": "option-kafka", "decision-order-storage": "option-postgres"},
    }
    canonical_after_initial = {
        path.relative_to(root / ".decision"): path.read_bytes()
        for path in (root / ".decision").rglob("*")
        if path.is_file()
    }
    assert canonical_after_initial == canonical_before

    created = client.post(
        "/api/v1/scenarios",
        json={"name": "Alt transport", "selections": {"decision-messaging-platform": "option-sqs"}},
    )
    assert created.status_code == 200
    created_record = created.json()
    second_created = client.post(
        "/api/v1/scenarios",
        json={"name": "beta transport", "selections": {"decision-messaging-platform": "option-kafka"}},
    )
    assert second_created.status_code == 200
    second_record = second_created.json()
    listed = client.get("/api/v1/scenarios")
    assert listed.status_code == 200
    listed_records = listed.json()
    assert len(listed_records) == len(initial_records) + 2
    new_ids = {created_record["id"], second_record["id"]}
    assert {record["id"] for record in listed_records} - {record["id"] for record in initial_records} == new_ids
    assert new_ids <= {record["id"] for record in listed_records}
    listed_created = next(record for record in listed_records if record["id"] == created_record["id"])
    assert listed_created == {"id": created_record["id"], "name": "Alt transport", "selections": {"decision-messaging-platform": "option-sqs"}}
    listed_second = next(record for record in listed_records if record["id"] == second_record["id"])
    assert listed_second == {"id": second_record["id"], "name": "beta transport", "selections": {"decision-messaging-platform": "option-kafka"}}
    assert [record["name"] for record in listed_records] == ["Alt transport", "beta transport", current["name"]]
    canonical_after_create = {
        path.relative_to(root / ".decision"): path.read_bytes()
        for path in (root / ".decision").rglob("*")
        if path.is_file()
    }
    assert set(canonical_after_create) - set(canonical_before) == {
        Path("scenarios") / f"{created_record['id']}.yaml",
        Path("scenarios") / f"{second_record['id']}.yaml",
    }
    assert all(canonical_after_create[path] == content for path, content in canonical_before.items())

    invalid_id = "scenario-invalid-selection"
    (root / ".decision/scenarios" / f"{invalid_id}.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "decision/v1",
                "record_type": "scenario",
                "id": invalid_id,
                "name": "Invalid selection",
                "selections": {"decision-messaging-platform": "option-missing"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    invalid = client.get("/api/v1/scenarios")
    assert invalid.status_code == 422
    assert invalid_id in invalid.json()["detail"]


def test_scenario_save_rejects_stale_repository_root_without_writing(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from switchplinth.api import create_app

    first_root = tmp_path / "first"
    first_root.mkdir()
    fixture_repository(first_root)
    second_root = tmp_path / "second"
    second_root.mkdir()
    fixture_repository(second_root)
    app = create_app(DecisionService(first_root, tmp_path / "cache"))
    app.state.workspace_root = tmp_path
    client = TestClient(app)

    switched = client.post("/api/v1/project/open", json={"path": "second"})
    assert switched.status_code == 200
    scenarios_before = {path.name for path in (second_root / ".decision/scenarios").glob("*.yaml")}
    stale = client.post(
        "/api/v1/scenarios",
        json={"name": "stale", "selections": {}, "expected_project_root": str(first_root)},
    )
    assert stale.status_code == 409
    assert {path.name for path in (second_root / ".decision/scenarios").glob("*.yaml")} == scenarios_before

    current = client.post(
        "/api/v1/scenarios",
        json={"name": "current", "selections": {}, "expected_project_root": str(second_root)},
    )
    assert current.status_code == 200
    assert (second_root / ".decision/scenarios" / f"{current.json()['id']}.yaml").is_file()


def test_save_connection_omits_blank_optional_fields_and_keeps_env_credential(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from switchplinth.api import create_app

    root = fixture_repository(tmp_path)
    service = DecisionService(root, tmp_path / "cache")
    response = TestClient(create_app(service)).post(
        "/api/v1/connections",
        json={
            "name": "Browser Gate Local",
            "id": "browser-gate-local",
            "provider": "openai_compatible",
            "endpoint": "http://host.docker.internal:17873/v1",
            "model": "gate-model",
            "capabilities": {"structured_output": True, "embeddings": False, "streaming": True},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": "browser-gate-local",
        "name": "Browser Gate Local",
        "provider": "openai_compatible",
        "endpoint": "http://host.docker.internal:17873/v1",
        "model": "gate-model",
        "capabilities": {"structured_output": True, "embeddings": False, "streaming": True},
    }
    saved = next(record for record in service.repository.records("connections") if record["id"] == "browser-gate-local")
    assert "embedding_model" not in saved
    assert "credential_ref" not in saved

    credential_response = TestClient(create_app(service)).post(
        "/api/v1/connections",
        json={
            "id": "browser-gate-with-credential",
            "provider": "openai_compatible",
            "model": "gate-model",
            "credential_ref": "env:MODEL_API_KEY",
        },
    )
    assert credential_response.status_code == 200
    credential_saved = next(
        record for record in service.repository.records("connections") if record["id"] == "browser-gate-with-credential"
    )
    assert credential_saved["credential_ref"] == "env:MODEL_API_KEY"


def test_repository_picker_limits_paths_and_switches_project_cache(tmp_path: Path) -> None:
    from switchplinth.api import create_app

    workspace = tmp_path / "repos"
    workspace.mkdir()
    project_root = workspace / "project"
    project_root.mkdir()
    repo = fixture_repository(project_root)
    service = DecisionService(repo, tmp_path / "initial-cache")
    app = create_app(service)
    app.state.workspace_root = workspace.resolve()
    app.state.cache_root = tmp_path / "cache"
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "escape").symlink_to(outside, target_is_directory=True)

    listing_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/repositories")
    listing = listing_route.endpoint()
    assert {item["path"] for item in listing["repositories"]} == {".", "project"}
    open_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/project/open")
    opened = open_route.endpoint(type("Request", (), {"path": "project"})())
    assert opened["project"]["root"] == str(repo.resolve())
    assert app.state.service.cache != tmp_path / "initial-cache"
    from fastapi import HTTPException
    for bad in ("../outside", str(outside), "escape"):
        with pytest.raises(HTTPException):
            open_route.endpoint(type("Request", (), {"path": bad})())


def test_source_route_reads_only_markdown_under_the_active_repository(tmp_path: Path) -> None:
    import os

    from fastapi import HTTPException
    from switchplinth.api import create_app

    workspace = tmp_path / "workspace"
    first = workspace / "first"
    second = workspace / "second"
    first.mkdir(parents=True)
    second.mkdir()
    (first / "design.md").write_text("# First repository\n\nOriginal document.\n", encoding="utf-8")
    (second / "design.md").write_text("# Second repository\n\nSwitched document.\n", encoding="utf-8")
    outside = tmp_path / "private.md"
    outside.write_text("Private workspace content.", encoding="utf-8")
    (first / "linked.md").symlink_to(outside)
    (first / "linked-directory").symlink_to(tmp_path, target_is_directory=True)
    (first / "notes.txt").write_text("Not Markdown.", encoding="utf-8")
    os.mkfifo(first / "pipe.md")

    app = create_app(DecisionService(first, tmp_path / "first-cache"))
    app.state.workspace_root = workspace.resolve()
    app.state.cache_root = tmp_path / "cache"
    source_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/source")
    open_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/v1/project/open")

    assert source_route.endpoint("design.md") == {
        "path": "design.md",
        "content": "# First repository\n\nOriginal document.\n",
    }
    for bad_path in ("../private.md", str(outside), "notes.txt", "linked.md", "linked-directory/private.md", "pipe.md"):
        with pytest.raises(HTTPException):
            source_route.endpoint(bad_path)
    with pytest.raises(HTTPException) as missing:
        source_route.endpoint("missing.md")
    assert missing.value.status_code == 404

    open_route.endpoint(type("Request", (), {"path": "second"})())
    assert source_route.endpoint("design.md")["content"] == "# Second repository\n\nSwitched document.\n"
    with pytest.raises(HTTPException) as old_document:
        source_route.endpoint("linked.md")
    assert old_document.value.status_code == 404


def test_fresh_markdown_repository_bootstraps_portable_overlay_then_scans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "fresh"
    root.mkdir()
    (root / "proposal.md").write_text("# Proposal\n\nThe team selected a careful queue strategy for durable message processing.\n", encoding="utf-8")
    service = DecisionService(root, tmp_path / "cache")
    assert (root / ".decision/schema/record-v1.schema.json").is_file()
    assert (root / ".decision/config.yaml").is_file()
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    result = service.scan()
    assert result["document_count"] == 1
    assert result["passage_count"] == 1
    service.repository.validate_references()


def test_qdrant_indexes_and_queries_are_isolated_by_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collections: dict[str, list[str]] = {}
    queried: list[str] = []
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda url, passages, graph, collection, **kwargs: collections.setdefault(collection, [item.id for item in passages]) and f"indexed {len(passages)}")
    def search(url: str, query: str, limit: int = 8, collection: str = "", **kwargs: object) -> list[dict[str, str]]:
        queried.append(collection)
        return []
    monkeypatch.setattr("switchplinth.service.qdrant_search", search)
    services = []
    for name, text_value in (("repo-a", "Repository Alpha contains unique architecture evidence for Queue Alpha."), ("repo-b", "Repository Beta contains unique architecture evidence for Queue Beta.")):
        root = tmp_path / name
        root.mkdir()
        (root / "notes.md").write_text(f"# Notes\n\n{text_value}\n", encoding="utf-8")
        service = DecisionService(root, tmp_path / "cache" / name)
        service.scan()
        services.append(service)
    result = services[0].search("Queue Alpha")
    assert services[0].qdrant_collection != services[1].qdrant_collection
    assert set(collections) == {service.qdrant_collection for service in services}
    assert queried[-1] == services[0].qdrant_collection
    assert result["grounded"] is True
    assert any("Queue Alpha" in item["text"] for item in result["evidence"])
    assert all("Queue Beta" not in item["text"] for item in result["evidence"])


def test_connection_env_pointer_is_persisted_and_option_validation_is_atomic(tmp_path: Path) -> None:
    root = fixture_repository(tmp_path)
    service = DecisionService(root, tmp_path / "cache")
    service.configure_connection({"id": "local", "provider": "openai_compatible", "endpoint": "http://localhost:1234/v1", "model": "small", "credential_ref": "env:LOCAL_TOKEN", "capabilities": {}})
    service.configure_connection({"id": "local", "provider": "openai_compatible", "endpoint": "http://localhost:1234/v1", "model": "small", "credential_ref": None, "capabilities": {}})
    assert service.connections["local"]["credential_ref"] == "env:LOCAL_TOKEN"
    messaging = next(record for record in service.repository.records("decisions") if record["id"] == "decision-messaging-platform")
    path = root / ".decision/decisions/messaging.yaml"
    original = path.read_bytes()
    candidate = {**messaging, "options": [{**option, "delta": {"base": "architecture", "operations": [{"op": "add_relationship", "relationship": {"id": "invalid-edge", "from": "missing", "to": "also-missing", "kind": "calls"}}]}} if option["id"] == "option-sqs" else option for option in messaging["options"]]}
    with pytest.raises(DomainError):
        service.repository.validate_candidate("decisions", candidate)
    assert path.read_bytes() == original


def test_qdrant_rebuild_writes_deterministic_points_and_query(monkeypatch: pytest.MonkeyPatch) -> None:
    import qdrant_client
    from types import SimpleNamespace
    from switchplinth.repository import evidence_anchor
    from switchplinth.store import qdrant_rebuild, qdrant_search

    calls = {"points": [], "query": None, "exists": False, "created": 0, "deleted": 0}

    class FakeClient:
        def __init__(self, **kwargs: object): pass
        def collection_exists(self, name: str) -> bool: return calls["exists"]
        def create_collection(self, **kwargs: object) -> None: calls.update(exists=True, created=calls["created"] + 1)
        def delete_collection(self, name: str) -> None: calls.update(exists=False, deleted=calls["deleted"] + 1)
        def upsert(self, **kwargs: object) -> None: calls["points"] = kwargs["points"]
        def query_points(self, **kwargs: object) -> object:
            calls["query"] = kwargs["query"]
            point = calls["points"][0]
            return SimpleNamespace(points=[SimpleNamespace(payload=point.payload, score=0.9)])

    monkeypatch.setattr(qdrant_client, "QdrantClient", FakeClient)
    passage = evidence_anchor("docs/a.md", ["A"], "Kafka handles ordered durable event replay.")
    graph = Graph({"kafka": Entity("kafka", "technology", "Kafka")})
    assert qdrant_rebuild("http://qdrant", [passage], graph).startswith("indexed 1")
    first_id = calls["points"][0].id
    assert qdrant_rebuild("http://qdrant", [passage], graph).startswith("indexed 1")
    assert calls["points"][0].id == first_id
    provider_vector = [0.25, 0.75]
    vectorizer = lambda text: provider_vector
    assert qdrant_rebuild("http://qdrant", [passage], graph, embedder=vectorizer).startswith("indexed 1")
    assert calls["points"][0].vector == provider_vector
    assert qdrant_search("http://qdrant", "ordered event replay", embedder=vectorizer)[0]["evidence_id"] == passage.id
    assert calls["query"] == provider_vector
    assert calls["created"] == 3 and calls["deleted"] == 2


def test_api_review_preserves_inference_and_scan_can_rebuild_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = fixture_repository(tmp_path)
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    monkeypatch.setattr("switchplinth.service.qdrant_search", lambda *args, **kwargs: [])
    service = DecisionService(root, tmp_path / "cache")
    stale_alias_record = next(alias for alias in service.repository.records("aliases") if alias.get("name") == "kafka" and alias.get("epistemic_state") == "inferred")
    stale_alias = root / ".decision/aliases" / f"{stale_alias_record['id']}.yaml"
    original_anchor = stale_alias_record["evidence"][0]
    stale_contents = stale_alias.read_text(encoding="utf-8")
    corrupted_contents = stale_contents.replace(f"- {original_anchor}", "- evidence-stale-anchor")
    assert corrupted_contents != stale_contents
    stale_alias.write_text(corrupted_contents, encoding="utf-8")
    reviewed_alias = next(alias for alias in service.repository.records_unchecked("aliases") if alias.get("reviewer") == "human")
    reviewed_alias_path = root / ".decision/aliases" / f"{reviewed_alias['id']}.yaml"
    reviewed_alias_bytes = reviewed_alias_path.read_bytes()
    scan_result = service.scan()
    assert scan_result["candidate_entity_count"] >= 2
    evidence_ids = {record["id"] for record in service.repository.records_unchecked("evidence")}
    assert all(set(record.get("evidence", [])) <= evidence_ids for record in service.repository.records_unchecked("aliases"))
    repaired_alias = next(alias for alias in service.repository.records_unchecked("aliases") if alias["id"] == stale_alias_record["id"])
    assert repaired_alias["evidence"] != ["evidence-stale-anchor"]
    assert reviewed_alias_path.read_bytes() == reviewed_alias_bytes
    original = root / ".decision/claims"
    original_claim = next(original.glob("*.yaml"))
    original_bytes = original_claim.read_bytes()
    existing_claim_count = len(list(original.glob("*.yaml")))
    review = service.review_claim(original_claim.stem, "confirmed")
    service.review_claim(review["id"], "rejected")
    final_review = service.review_claim(original_claim.stem, "confirmed")
    assert final_review["epistemic_state"] == "confirmed"
    assert review["id"] in final_review["supersedes"]
    assert original_claim.read_bytes() == original_bytes
    assert len(list(original.glob("*.yaml"))) == existing_claim_count + 3
    assert any(claim.id == final_review["id"] for claim in service.graph()[4] if claim.epistemic_state == "confirmed")
    inferred_alias = repaired_alias
    alias_path = root / ".decision/aliases" / f"{inferred_alias['id']}.yaml"
    alias_bytes = alias_path.read_bytes()
    rejected_alias = service.review_alias(inferred_alias["id"], "rejected")
    confirmed_alias = service.review_alias(inferred_alias["id"], "confirmed")
    assert rejected_alias["id"] in confirmed_alias["supersedes"]
    query = service.search("Why are we using Kafka?")
    assert query["grounded"] is True
    assert query["evidence"]
    assert "Replay and ordering" in query["answer"]
    assert any(item["source"] == "examples/synthetic/decisions/messaging.md" for item in query["evidence"])
    assert all("README" not in item["source"] and "PORTABLE_FORMAT" not in item["source"] for item in query["evidence"])
    assert query["claims"], "a grounded why answer must expose at least one supporting claim"
    returned_evidence_ids = {item["id"] for item in query["evidence"]}
    assert all(set(claim["evidence"]) & returned_evidence_ids for claim in query["claims"])
    assert returned_evidence_ids <= {evidence_id for claim in query["claims"] for evidence_id in claim["evidence"]}
    with service.index.connect() as db:
        assert returned_evidence_ids <= {row[0] for row in db.execute("SELECT id FROM passages")}
    service.index.path.unlink()
    service.index = SearchIndex(service.cache / "index.sqlite3")
    service.scan()
    assert alias_path.read_bytes() == alias_bytes
    effective = effective_aliases(service.repository.records("aliases"))
    assert any(alias["id"] == confirmed_alias["id"] for alias in effective)
    assert any(alias["id"] == "alias-kafka" for alias in effective)
    assert any(claim.id == final_review["id"] for claim in service.graph()[4] if claim.epistemic_state == "confirmed")
    rebuilt = service.search("Why are we using Kafka?")
    assert rebuilt["grounded"] is True
    rebuilt_ids = {item["id"] for item in rebuilt["evidence"]}
    assert rebuilt_ids <= {evidence_id for claim in rebuilt["claims"] for evidence_id in claim["evidence"]}
    with service.index.connect() as db:
        assert db.execute("SELECT value FROM index_metadata WHERE key='index_version'").fetchone()[0] == "1"


def test_why_search_without_claim_support_is_not_grounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = fixture_repository(tmp_path)
    monkeypatch.setattr("switchplinth.service.qdrant_search", lambda *args, **kwargs: [])
    service = DecisionService(root, tmp_path / "cache")
    for claim_path in (root / ".decision/claims").glob("*.yaml"):
        claim_path.unlink()

    answer = service.search("Why are we using Kafka?")

    assert answer["evidence"]
    assert answer["claims"] == []
    assert answer["grounded"] is False
    assert "no current claim supports" in answer["answer"].casefold()


def test_why_search_does_not_use_same_passage_unrelated_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = fixture_repository(tmp_path)
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    monkeypatch.setattr("switchplinth.service.qdrant_search", lambda *args, **kwargs: [])
    service = DecisionService(root, tmp_path / "cache")
    service.scan()
    for claim_path in (root / ".decision/claims").glob("*.yaml"):
        claim_path.unlink()
    passage_id = next(option["evidence"][0] for decision in service.repository.records("decisions") for option in decision["options"] if option["id"] == "option-kafka")
    service.repository.save("claims", {
        "schema_version": "decision/v1",
        "record_type": "claim",
        "id": "claim-unrelated-same-passage",
        "subject": "service-order",
        "predicate": "supports",
        "object": "an unrelated assertion",
        "epistemic_state": "confirmed",
        "confidence": 1.0,
        "evidence": [passage_id],
    })

    answer = service.search("Why Kafka?")

    assert answer["evidence"]
    assert answer["claims"] == []
    assert answer["grounded"] is False


def test_inactive_why_search_excludes_stale_and_nonindexed_claim_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = fixture_repository(tmp_path)
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    monkeypatch.setattr("switchplinth.service.qdrant_search", lambda *args, **kwargs: [])
    service = DecisionService(root, tmp_path / "cache")
    service.scan()
    for claim_path in (root / ".decision/claims").glob("*.yaml"):
        claim_path.unlink()
    decision = next(record for record in service.repository.records("decisions") if record["id"] == "decision-messaging-platform")
    option = next(item for item in decision["options"] if item["id"] == "option-kafka")
    # The scan fixture also extracts a second Kafka option under another ID.
    # Remove that duplicate option so the inactive legacy identity is unambiguous.
    for record in service.repository.records("decisions"):
        if record["id"] == decision["id"]:
            continue
        adds_kafka = any(
            operation.get("op") in {"add_entity", "replace_entity"}
            and operation.get("entity", {}).get("name", "").casefold() == "apache kafka"
            for candidate in record.get("options", [])
            for operation in candidate.get("delta", {}).get("operations", [])
        )
        if adds_kafka:
            (root / ".decision/decisions" / f"{record['id']}.yaml").unlink()
    extracted_kafka_ids = {
        entity["id"] for entity in service.repository.records("entities")
        if entity.get("name", "").casefold() == "apache kafka"
    }
    for alias in service.repository.records("aliases"):
        if alias.get("entity_id") in extracted_kafka_ids:
            (root / ".decision/aliases" / f"{alias['id']}.yaml").unlink()
    evidence_records = service.repository.records("evidence")
    all_ids = [record["id"] for record in evidence_records]
    with service.index.connect() as db:
        indexed_ids = {row[0] for row in db.execute("SELECT id FROM passages")}
    unique_ids = {evidence_id for evidence_id in all_ids if all_ids.count(evidence_id) == 1}
    stale_id = next(evidence_id for evidence_id in unique_ids & indexed_ids if evidence_id not in option["evidence"])
    nonindexed_id = next(evidence_id for evidence_id in unique_ids & indexed_ids if evidence_id not in option["evidence"] and evidence_id != stale_id)
    stale_record = next(record for record in service.repository.records("evidence") if record["id"] == stale_id)
    service.repository.save("evidence", {**stale_record, "state": "unresolved"})
    assert next(record for record in service.repository.records("evidence") if record["id"] == stale_id)["state"] == "unresolved"
    with service.index.connect() as db:
        db.execute("DELETE FROM passages WHERE id = ?", (nonindexed_id,))
        db.execute("DELETE FROM passage_fts WHERE id = ?", (nonindexed_id,))
    service.repository.save("claims", {
        "schema_version": "decision/v1",
        "record_type": "claim",
        "id": "claim-stale-and-nonindexed",
        "subject": "broker-kafka",
        "predicate": "supports",
        "object": "the historical choice",
        "epistemic_state": "confirmed",
        "confidence": 1.0,
        "evidence": [stale_id, nonindexed_id],
    })

    answer = service.search("Why Kafka?", {decision["id"]: "option-sqs"})

    assert "scenario_context" in answer
    # The stale and non-indexed claim citations never support the answer.
    assert answer["claims"] == []
    assert answer["evidence"]
    assert not {stale_id, nonindexed_id}.intersection(item["id"] for item in answer["evidence"])
    # option-kafka's own current, indexed evidence grounds the unselected-option answer.
    assert {item["id"] for item in answer["evidence"]} <= set(option["evidence"] or decision["evidence"])
    assert answer["grounded"] is True
    assert "No current claim supports" not in answer["answer"]


def test_inactive_why_search_finds_support_after_eight_candidate_passages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = fixture_repository(tmp_path)
    (root / "docs/retrieval-fixture.md").write_text(
        "# Kafka retrieval fixture\n\nWhy do we use Kafka? It supports durable replay for the event platform.\n\n"
        "## Kafka operations\n\nKafka keeps event delivery reliable through controlled retries and monitoring.\n\n"
        "## Kafka replay\n\nKafka replay lets operators recover events after a service interruption.\n\n"
        "## Kafka retention\n\nKafka retains event history long enough for downstream recovery.\n\n"
        "## Kafka ordering\n\nKafka preserves event ordering for consumers that rebuild their state.\n\n"
        "## Kafka throughput\n\nKafka handles event throughput while keeping durable delivery available.\n\n"
        "## Kafka consumers\n\nKafka consumers can resume from saved offsets after maintenance.\n\n"
        "## Kafka platform\n\nKafka provides the event platform with durable replay across deployments.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    monkeypatch.setattr("switchplinth.service.qdrant_search", lambda *args, **kwargs: [])
    service = DecisionService(root, tmp_path / "cache")
    service.scan()
    for claim_path in (root / ".decision/claims").glob("*.yaml"):
        claim_path.unlink()
    # The scan extracts a duplicate Messaging choice decision whose selected
    # option adds an active "Apache Kafka" entity with the alias "Kafka". A
    # selected exact match outranks the unselected one, so remove those aliases
    # to keep this test on the inactive answer for broker-kafka.
    extracted_kafka_ids = {
        entity["id"] for entity in service.repository.records("entities")
        if entity.get("name", "").casefold() == "apache kafka"
    }
    for alias in service.repository.records("aliases"):
        if alias.get("entity_id") in extracted_kafka_ids:
            (root / ".decision/aliases" / f"{alias['id']}.yaml").unlink()
    decision = next(record for record in service.repository.records("decisions") if record["id"] == "decision-messaging-platform")
    option = next(item for item in decision["options"] if item["id"] == "option-kafka")
    ranked_hits = service.index.search("Why Kafka?", limit=100)
    evidence_records = service.repository.records("evidence")
    unresolved_ids = {record["id"] for record in evidence_records if record.get("state", "current") != "current"}
    current_ids = {
        record["id"]
        for record in evidence_records
        if record.get("state", "current") == "current" and record["id"] not in unresolved_ids
    }
    with service.index.connect() as db:
        indexed_ids = {row[0] for row in db.execute("SELECT id FROM passages")}
    eligible_ids = current_ids & indexed_ids
    hit_ids = [hit["id"] for hit in ranked_hits if hit["id"] in eligible_ids]
    late_support_ids = sorted(eligible_ids - set(hit_ids))
    assert len(hit_ids) >= 8 and late_support_ids
    supporting_id = late_support_ids[-1]
    option["evidence"] = [*hit_ids[:8], supporting_id]
    service.repository.save("decisions", decision)
    service.repository.save("claims", {
        "schema_version": "decision/v1",
        "record_type": "claim",
        "id": "claim-supports-late-passage",
        "subject": "broker-kafka",
        "predicate": "supports",
        "object": "the historical choice",
        "epistemic_state": "confirmed",
        "confidence": 1.0,
        "evidence": [supporting_id],
    })

    answer = service.search("Why Kafka?", {decision["id"]: "option-sqs"})

    assert "scenario_context" in answer
    assert answer["grounded"] is True
    assert [claim["id"] for claim in answer["claims"]] == ["claim-supports-late-passage"]
    assert supporting_id in {item["id"] for item in answer["evidence"]}
    returned_ids = {item["id"] for item in answer["evidence"]}
    assert returned_ids <= {evidence_id for claim in answer["claims"] for evidence_id in claim["evidence"]}


def test_scan_restores_portable_files_when_a_write_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = fixture_repository(tmp_path)
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs/scan.md").write_text("We chose Apache Kafka because replay must remain available.", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    service = DecisionService(root, tmp_path / "cache")
    before = {path.relative_to(root / ".decision"): path.read_bytes() for path in (root / ".decision").rglob("*") if path.is_file()}
    original_save = service.repository.save
    writes = 0
    def fail_after_first_write(kind: str, record: dict[str, object]) -> Path:
        nonlocal writes
        path = original_save(kind, record)
        writes += 1
        if writes == 1:
            raise OSError("simulated write failure")
        return path
    monkeypatch.setattr(service.repository, "save", fail_after_first_write)
    with pytest.raises(OSError, match="simulated write failure"):
        service.scan()
    after = {path.relative_to(root / ".decision"): path.read_bytes() for path in (root / ".decision").rglob("*") if path.is_file()}
    assert after == before


def test_deterministic_embeddings_and_unconfigured_provider_capabilities() -> None:
    assert hashed_embedding("Kafka events replay") == hashed_embedding("Kafka events replay")
    assert len(hashed_embedding("some text")) == 256


def test_hosted_provider_connections_ignore_stale_local_endpoint(tmp_path: Path) -> None:
    service = DecisionService(fixture_repository(tmp_path), tmp_path / "cache")
    saved = service.configure_connection({"id": "hosted", "provider": "openai", "endpoint": "http://host.docker.internal:11434/v1", "model": "gpt-test"})
    assert saved["endpoint"] == ""
    assert service.connections["hosted"]["endpoint"] == ""


def test_anthropic_unprobed_capabilities_are_marked_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from switchplinth.providers import diagnose

    urls: list[str] = []

    def get(url: str, **kwargs: object) -> SimpleNamespace:
        urls.append(url)
        return SimpleNamespace(status_code=200, json=lambda: {"data": [{"id": "claude-test"}]}, text="")

    monkeypatch.setattr("switchplinth.providers.httpx.get", get)
    diagnostic = diagnose({"id": "anthropic", "provider": "anthropic", "endpoint": "http://host.docker.internal:11434/v1", "model": "claude-test"})
    assert urls == ["https://api.anthropic.com/v1/models"]
    assert diagnostic["capabilities"]["structured_output"]["status"] == "error"
    assert diagnostic["capabilities"]["structured_output"]["normalized_error"] == "capability_probe_not_implemented"
    assert diagnostic["capabilities"]["streaming"]["status"] == "error"
    assert diagnostic["capabilities"]["embeddings"]["status"] == "unsupported"


def test_configured_provider_embeddings_are_used_for_index_and_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "notes.md").write_text("# Notes\n\nA semantic embedding provider should index this architecture evidence.\n", encoding="utf-8")
    indexed: list[list[float]] = []
    queried: list[list[float]] = []

    def vectorize(connection: dict[str, object], text: str) -> list[float]:
        return [float(len(text)), 1.0]

    def rebuild(url: str, passages: list[object], graph: Graph, collection: str, embedder: object = None) -> str:
        indexed.extend(embedder(item.text) for item in passages)
        return f"indexed {len(indexed)} passages"

    def search(url: str, query: str, limit: int = 8, collection: str = "", embedder: object = None, diagnostics: dict[str, str] | None = None) -> list[dict[str, object]]:
        queried.append(embedder(query))
        diagnostics.update(status="supported", detail="provider vector query passed")
        return []

    monkeypatch.setattr("switchplinth.service.embed_with_litellm", vectorize)
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", rebuild)
    monkeypatch.setattr("switchplinth.service.qdrant_search", search)
    service = DecisionService(root, tmp_path / "cache")
    service.configure_connection({"id": "semantic", "provider": "openai_compatible", "endpoint": "http://127.0.0.1:1/v1", "model": "chat", "embedding_model": "embed", "capabilities": {"embeddings": True}})
    scan = service.scan()
    result = service.search("Why does the architecture use embeddings?")
    assert scan["embedding"]["status"] == "supported"
    assert scan["embedding"]["mode"] == "provider"
    assert indexed and queried
    assert all(len(vector) == 2 for vector in indexed + queried)
    assert result["semantic_index"]["status"] == "supported"


def test_openai_compatible_litellm_path_against_local_http_server(monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from switchplinth.providers import diagnose, embed_with_litellm, extract_with_litellm, provider_endpoint

    captured: dict[str, object] = {"requests": [], "authorizations": []}
    extraction_json = {"entities": [], "decisions": []}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args: object) -> None:
            return
        def do_GET(self) -> None:
            if self.headers.get("Authorization") != "Bearer local-test-token":
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b"unauthorized")
                return
            payload = {"data": [{"id": "test-model"}, {"id": "test-embedding"}]}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured["authorization"] = self.headers.get("Authorization")
            captured["authorizations"].append(self.headers.get("Authorization"))
            captured["body"] = body
            captured["requests"].append(body)
            if self.path.endswith("/embeddings"):
                response = {"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}], "model": "test-embedding"}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
                return
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')
                return
            response = {"id": "chatcmpl-local", "object": "chat.completion", "created": 1, "model": "test-model", "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(extraction_json)}, "finish_reason": "stop"}]}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except PermissionError:
        pytest.skip("sandbox policy does not allow a loopback mock server; run this test with network namespace access")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("MOCK_LLM_KEY", "local-test-token")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    connection = {"id": "local", "provider": "openai_compatible", "endpoint": f"http://127.0.0.1:{server.server_port}/v1", "model": "test-model", "credential_ref": "env:MOCK_LLM_KEY"}
    try:
        diagnostic = diagnose(connection)
        assert diagnostic["capabilities"]["authentication"]["status"] == "supported"
        assert diagnostic["capabilities"]["endpoint"]["status"] == "supported"
        assert diagnostic["capabilities"]["model"]["status"] == "supported"
        assert diagnostic["capabilities"]["structured_output"]["status"] == "supported"
        assert diagnostic["capabilities"]["embeddings"]["status"] == "unsupported"
        assert diagnostic["capabilities"]["streaming"]["status"] == "supported"
        keyless_connection = {key: value for key, value in connection.items() if key != "credential_ref"}
        assert extract_with_litellm(keyless_connection, "A local test source passage.") == extraction_json
        assert captured["authorizations"][-1] == "Bearer no-key-required"
        keyless_embedding = {**keyless_connection, "embedding_model": "test-embedding"}
        assert embed_with_litellm(keyless_embedding, "portable semantic query") == [0.1, 0.2, 0.3]
        assert captured["authorizations"][-1] == "Bearer no-key-required"
        missing_embedding = diagnose({**connection, "capabilities": {"embeddings": True}})
        assert missing_embedding["capabilities"]["embeddings"]["status"] == "unsupported"
        assert missing_embedding["capabilities"]["embeddings"]["normalized_error"] == "embedding_model_not_configured"
        embedding_connection = {**connection, "capabilities": {"embeddings": True}, "embedding_model": "test-embedding"}
        embedding_diagnostic = diagnose(embedding_connection)
        assert embedding_diagnostic["capabilities"]["embeddings"]["status"] == "supported"
        assert embed_with_litellm(embedding_connection, "portable semantic query") == [0.1, 0.2, 0.3]
        assert any(request.get("model") == "test-embedding" for request in captured["requests"])
        assert extract_with_litellm(connection, "A local test source passage.") == extraction_json
        assert captured["authorization"] == "Bearer local-test-token"
        assert captured["body"]["response_format"] == {"type": "json_object"}
        prompt = captured["body"]["messages"][0]["content"]
        assert "optional precondition expect:{} or expect:{exists:boolean}" in prompt
        assert any(request.get("response_format") == {"type": "json_object"} for request in captured["requests"])
        assert any(request.get("stream") is True for request in captured["requests"])
        missing_model = diagnose({**connection, "model": "not-listed"})
        assert missing_model["capabilities"]["model"]["raw_error"]
        assert missing_model["capabilities"]["model"]["normalized_error"] == "model_unavailable"
        unauthorized = diagnose({**connection, "credential_ref": "env:MISSING_TEST_TOKEN"})
        assert unauthorized["capabilities"]["authentication"]["status"] == "error"
        assert "401" in unauthorized["capabilities"]["authentication"]["raw_error"]
        assert unauthorized["capabilities"]["authentication"]["normalized_error"] == "invalid_credentials"
        assert unauthorized["capabilities"]["endpoint"]["status"] == "supported"
        assert unauthorized["capabilities"]["endpoint"]["normalized_error"] is None
        assert unauthorized["capabilities"]["model"]["normalized_error"] == "invalid_credentials"
        assert provider_endpoint({"provider": "openai", "endpoint": "http://host.docker.internal:11434/v1"}) == "https://api.openai.com/v1"
        assert provider_endpoint({"provider": "anthropic", "endpoint": "http://host.docker.internal:11434/v1"}) == "https://api.anthropic.com"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_delta_proposal_uses_keyless_local_auth_and_preserves_env_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    from types import SimpleNamespace

    import litellm
    from switchplinth.providers import KEYLESS_OPENAI_COMPATIBLE_API_KEY, propose_delta_with_litellm

    captured: list[dict[str, object]] = []
    payload = {"delta": {"base": "architecture", "operations": []}, "rationale": "", "warnings": []}

    def completion(**kwargs: object) -> SimpleNamespace:
        captured.append(kwargs)
        message = SimpleNamespace(content=json.dumps(payload))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(litellm, "completion", completion)
    local_connection = {
        "id": "local", "provider": "openai_compatible", "endpoint": "http://127.0.0.1:1234/v1", "model": "test-model",
    }
    proposal = propose_delta_with_litellm(local_connection, {"id": "decision"}, {"id": "option"}, "Keep it", {})
    assert proposal == payload
    assert captured[-1]["api_base"] == local_connection["endpoint"]
    assert captured[-1]["api_key"] == KEYLESS_OPENAI_COMPATIBLE_API_KEY

    monkeypatch.setenv("MODEL_API_KEY_FOR_TEST", "local-test-token")
    authenticated_connection = {**local_connection, "credential_ref": "env:MODEL_API_KEY_FOR_TEST"}
    proposal = propose_delta_with_litellm(authenticated_connection, {"id": "decision"}, {"id": "option"}, "Keep it", {})
    assert proposal == payload
    assert captured[-1]["api_key"] == "local-test-token"


def test_mcp_streamable_http_initializes_and_lists_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import json
    import httpx
    from switchplinth.api import create_app

    root = fixture_repository(tmp_path)
    service = DecisionService(root, tmp_path / "cache")
    monkeypatch.setattr("switchplinth.service.qdrant_search", lambda *args, **kwargs: [])
    app = create_app(service)

    def response_json(response: httpx.Response) -> dict[str, object]:
        if "json" in response.headers.get("content-type", ""):
            return response.json()
        data_line = next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
        return json.loads(data_line)

    async def exercise() -> None:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
                headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
                initialized = await client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test-client", "version": "1"}}})
                assert initialized.status_code == 200
                assert response_json(initialized)["result"]["serverInfo"]["name"] == "io.github.bcmyguest/switchplinth"
                session_id = initialized.headers["mcp-session-id"]
                session_headers = headers | {"Mcp-Session-Id": session_id, "MCP-Protocol-Version": "2025-03-26"}
                notification = await client.post("/mcp", headers=session_headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
                assert notification.status_code in {200, 202}
                listed = await client.post("/mcp", headers=session_headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                assert listed.status_code == 200
                tool_names = {tool["name"] for tool in response_json(listed)["result"]["tools"]}
                assert tool_names == {"list_decisions", "search_decisions", "inspect_architecture", "inspect_entity", "diff_scenarios"}

    asyncio.run(exercise())


def test_mcp_scenario_reads_match_http_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import json
    import httpx
    from switchplinth.api import create_app

    root = fixture_repository(tmp_path)
    service = DecisionService(root, tmp_path / "cache")
    monkeypatch.setattr("switchplinth.service.qdrant_search", lambda *args, **kwargs: [])
    app = create_app(service)

    def response_json(response: httpx.Response) -> dict[str, object]:
        if "json" in response.headers.get("content-type", ""):
            return response.json()
        data_line = next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
        return json.loads(data_line)

    def decision_hashes() -> dict[str, str]:
        return {
            path.relative_to(tmp_path / ".decision").as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((tmp_path / ".decision").rglob("*"))
            if path.is_file()
        }

    def tool_result(response: httpx.Response) -> tuple[dict[str, object], str]:
        result = response_json(response)["result"]
        if "structuredContent" in result:
            return result["structuredContent"], "structuredContent"
        return json.loads(result["content"][0]["text"]), "content[0].text"

    before = decision_hashes()
    selections = {"decision-messaging-platform": "option-sqs"}

    async def exercise() -> str:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
                headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
                initialized = await client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test-client", "version": "1"}}})
                assert initialized.status_code == 200
                session_id = initialized.headers["mcp-session-id"]
                session_headers = headers | {"Mcp-Session-Id": session_id, "MCP-Protocol-Version": "2025-03-26"}
                notification = await client.post("/mcp", headers=session_headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
                assert notification.status_code in {200, 202}

                architecture_response = await client.post("/mcp", headers=session_headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "inspect_architecture", "arguments": {"selections": selections}}})
                assert architecture_response.status_code == 200
                architecture, result_field = tool_result(architecture_response)
                assert architecture == service.graph_json(selections)
                entity_ids = {entity["id"] for entity in architecture["entities"]}
                assert "queue-sqs-orders" in entity_ids
                assert "broker-kafka" not in entity_ids

                entity_response = await client.post("/mcp", headers=session_headers, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "inspect_entity", "arguments": {"entity_id": "queue-sqs-orders", "selections": selections}}})
                assert entity_response.status_code == 200
                entity, entity_result_field = tool_result(entity_response)
                assert entity == service.entity_detail("queue-sqs-orders", selections)
                assert entity["decisions"][0]["selected_option"]["id"] == "option-sqs"

                unknown_response = await client.post("/mcp", headers=session_headers, json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "inspect_entity", "arguments": {"entity_id": "no-such-entity"}}})
                assert unknown_response.status_code == 200
                unknown_result = response_json(unknown_response)["result"]
                assert unknown_result["isError"] is True
                assert "no-such-entity" in json.dumps(unknown_result)
                return f"{result_field}, {entity_result_field}"

    result_fields = asyncio.run(exercise())
    assert decision_hashes() == before
    assert result_fields in {"structuredContent, structuredContent", "content[0].text, content[0].text"}

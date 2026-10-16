"""Local-model extraction follow-ups: confidence robustness and entity references in deltas."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from switchplinth.domain import stable_id
from switchplinth.service import DecisionService

QUOTE = "The Payments Service publishes retry jobs to Amazon SQS instead of Apache Kafka."


@pytest.fixture
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DecisionService:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs/payments.md").write_text(f"# Payment retries\n\n{QUOTE}\n", encoding="utf-8")
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    decision_service = DecisionService(root, tmp_path / "cache")
    decision_service.configure_connection({"id": "test", "provider": "mock", "model": "mock-model"})
    return decision_service


def _respond(monkeypatch: pytest.MonkeyPatch, *responses: dict[str, Any]) -> list[str]:
    prompts: list[str] = []
    queue = list(responses)

    def extract(_connection: dict[str, Any], prompt: str) -> dict[str, Any]:
        prompts.append(prompt)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr("switchplinth.service.extract_with_litellm", extract)
    return prompts


def test_invalid_alias_confidence_keeps_the_extraction_and_reports_it(service: DecisionService, monkeypatch: pytest.MonkeyPatch) -> None:
    _respond(monkeypatch, {"entities": [
        {"name": "Amazon SQS", "kind": "queue", "aliases": ["SQS"], "confidence": 0.9, "alias_confidence": [], "evidence_quote": QUOTE},
        {"name": "Apache Kafka", "kind": "queue", "aliases": ["Kafka"], "alias_confidence": [{"value": 0.8}], "evidence_quote": QUOTE},
        {"name": "Payments Service", "kind": "service", "aliases": ["Payments"], "alias_confidence": 7, "evidence_quote": QUOTE},
    ]})

    result = service.extract_with_provider("test")

    assert {entity["name"] for entity in result["entities"]} == {"Amazon SQS", "Apache Kafka", "Payments Service"}
    assert {(alias["name"], alias["confidence"]) for alias in result["aliases"]} == {("SQS", 0.65), ("Kafka", 0.65), ("Payments", 0.65)}
    assert len([item for item in result["diagnostics"] if "alias_confidence" in item]) == 3


def _entities() -> list[dict[str, Any]]:
    return [
        {"name": "Payments Service", "kind": "service", "evidence_quote": QUOTE},
        {"name": "Amazon SQS", "kind": "queue", "aliases": ["SQS"], "evidence_quote": QUOTE},
    ]


def _decision(*operations: dict[str, Any]) -> dict[str, Any]:
    return {"title": "Payment retry transport", "evidence_quote": QUOTE, "options": [
        {"title": "Amazon SQS", "selected": True, "evidence_quote": QUOTE, "delta": {"base": "architecture", "operations": list(operations)}},
        {"title": "Apache Kafka", "selected": False, "evidence_quote": QUOTE, "delta": {"base": "architecture", "operations": []}},
    ]}


def _edge(source: str, target: str, edge_id: str = "payments-retry-edge") -> dict[str, Any]:
    return {"op": "add_relationship", "relationship": {"id": edge_id, "from": source, "to": target, "kind": "publishes_to"}}


def test_delta_entity_names_and_aliases_map_to_entity_ids(service: DecisionService, monkeypatch: pytest.MonkeyPatch) -> None:
    worker = {"op": "add_entity", "entity": {"id": "retry-worker", "kind": "service", "name": "Retry Worker"}}
    prompts = _respond(monkeypatch, {"entities": _entities(), "decisions": [_decision(
        _edge("  payments   SERVICE ", "SQS"),
        worker,
        _edge("Retry Worker", "Amazon SQS", "worker-edge"),
    )]})

    result = service.extract_with_provider("test")

    assert len(prompts) == 1
    decision = result["decisions"][0]
    assert "extraction_review" not in decision
    operations = decision["options"][0]["delta"]["operations"]
    assert operations[0]["relationship"]["from"] == stable_id("entity", "payments service")
    assert operations[0]["relationship"]["to"] == stable_id("entity", "amazon sqs")
    assert operations[2]["relationship"]["from"] == "retry-worker"
    assert operations[2]["relationship"]["to"] == stable_id("entity", "amazon sqs")


def test_ambiguous_entity_name_is_never_guessed_and_triggers_one_named_retry(service: DecisionService, monkeypatch: pytest.MonkeyPatch) -> None:
    entities = [*_entities(), {"name": "Amazon SQS Dead Letters", "kind": "queue", "aliases": ["sqs"], "evidence_quote": QUOTE}]
    response = {"entities": entities, "decisions": [_decision(_edge("Payments Service", "SQS"))]}
    prompts = _respond(monkeypatch, response)

    result = service.extract_with_provider("test")

    assert len(prompts) == 2
    assert "CORRECTION REQUIRED" in prompts[1] and "'SQS' is ambiguous" in prompts[1]
    review = result["decisions"][0]["extraction_review"]
    assert review["attempts"] == 2
    assert review["rejected_options"][0]["delta"]["operations"][0]["relationship"]["to"] == "SQS"
    assert all(option["delta"]["operations"] == [] for option in result["decisions"][0]["options"])


def test_unknown_entity_name_is_named_in_retry_and_a_corrected_reply_is_mapped(service: DecisionService, monkeypatch: pytest.MonkeyPatch) -> None:
    first = {"entities": _entities(), "decisions": [_decision(_edge("Payments Service", "Retry Queue Cluster"))]}
    corrected = {"entities": _entities(), "decisions": [_decision(_edge("Payments Service", "Amazon SQS"))]}
    prompts = _respond(monkeypatch, first, corrected)

    result = service.extract_with_provider("test")

    assert len(prompts) == 2 and "unknown entity reference 'Retry Queue Cluster'" in prompts[1]
    decision = result["decisions"][0]
    assert "extraction_review" not in decision
    assert decision["options"][0]["delta"]["operations"][0]["relationship"]["to"] == stable_id("entity", "amazon sqs")


def test_prompt_lists_known_entity_ids_with_names(service: DecisionService, monkeypatch: pytest.MonkeyPatch) -> None:
    service.repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "payments", "kind": "service", "name": "Payments Service"})
    prompts = _respond(monkeypatch, {"entities": [], "decisions": [_decision(_edge("payments service", "payments"))]})

    result = service.extract_with_provider("test")

    assert "payments: Payments Service" in prompts[0]
    assert len(prompts) == 1
    assert result["decisions"][0]["options"][0]["delta"]["operations"][0]["relationship"]["from"] == "payments"


def test_unknown_id_shaped_reference_retries_with_the_valid_references_when_entities_exist(service: DecisionService, monkeypatch: pytest.MonkeyPatch) -> None:
    first = {"entities": _entities(), "decisions": [_decision(_edge("payments-service", "Amazon SQS"))]}
    corrected = {"entities": _entities(), "decisions": [_decision(_edge("Payments Service", "Amazon SQS"))]}
    prompts = _respond(monkeypatch, first, corrected)

    result = service.extract_with_provider("test")

    assert len(prompts) == 2
    assert "unknown entity reference 'payments-service'" in prompts[1]
    assert f"{stable_id('entity', 'payments service')}: Payments Service" in prompts[1]
    assert result["decisions"][0]["options"][0]["delta"]["operations"][0]["relationship"]["from"] == stable_id("entity", "payments service")


def test_rejected_alias_is_not_used_to_map_a_delta_reference(service: DecisionService, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_id = service.repository.records("evidence")[0]["id"] if service.repository.records("evidence") else None
    if evidence_id is None:
        service.scan()
        evidence_id = service.repository.records("evidence")[0]["id"]
    service.repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "payments", "kind": "service", "name": "Payments Service"})
    service.repository.save("aliases", {"schema_version": "decision/v1", "record_type": "alias", "id": "alias-pay", "entity_id": "payments", "name": "Pay", "epistemic_state": "inferred", "confidence": 0.6, "evidence": [evidence_id]})
    service.review_alias("alias-pay", "rejected")
    prompts = _respond(monkeypatch, {"entities": [], "decisions": [_decision(_edge("Pay", "payments"))]})

    result = service.extract_with_provider("test")

    assert len(prompts) == 2 and "unknown entity reference 'Pay'" in prompts[1]
    assert result["decisions"][0]["extraction_review"]["rejected_options"][0]["delta"]["operations"][0]["relationship"]["from"] == "Pay"


def test_empty_alias_confidence_without_aliases_is_silent(service: DecisionService, monkeypatch: pytest.MonkeyPatch) -> None:
    _respond(monkeypatch, {"entities": [{"name": "Amazon SQS", "kind": "queue", "aliases": [], "alias_confidence": {}, "evidence_quote": QUOTE}]})

    result = service.extract_with_provider("test")

    assert result["entity_count"] == 1
    assert not [item for item in result["diagnostics"] if "alias_confidence" in item]


def test_alias_confidence_map_applies_per_alias_only_for_exact_returned_aliases(service: DecisionService, monkeypatch: pytest.MonkeyPatch) -> None:
    _respond(monkeypatch, {"entities": [
        {"name": "Amazon SQS", "kind": "queue", "aliases": ["SQS", "Simple Queue"], "alias_confidence": {"SQS": 0.95, "Simple Queue": 0.7}, "evidence_quote": QUOTE},
        {"name": "Apache Kafka", "kind": "queue", "aliases": ["Kafka"], "alias_confidence": {"kafka": 0.9}, "evidence_quote": QUOTE},
    ]})

    result = service.extract_with_provider("test")

    assert {(alias["name"], alias["confidence"]) for alias in result["aliases"]} == {("SQS", 0.95), ("Simple Queue", 0.7), ("Kafka", 0.65)}
    assert len([item for item in result["diagnostics"] if "alias_confidence" in item]) == 1

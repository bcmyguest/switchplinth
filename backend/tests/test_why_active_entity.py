"""A why query names the selected choice before unselected alternatives."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from switchplinth.service import DecisionService

FIXTURE_BOOTSTRAP = Path(__file__).resolve().parents[2] / "fixtures" / "food-delivery" / "bootstrap.py"


def _bootstrap(root: Path) -> None:
    spec = importlib.util.spec_from_file_location("food_delivery_bootstrap_why", FIXTURE_BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.bootstrap(root)


def test_why_kafka_reports_selected_order_events_before_unselected_payment_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "food-delivery"
    _bootstrap(root)
    monkeypatch.setattr("switchplinth.service.qdrant_search", lambda *args, **kwargs: [])
    service = DecisionService(root, tmp_path / ".food-delivery-decision-cache")

    answer = service.search("Why Kafka?")

    text = answer["answer"]
    assert "Apache Kafka was selected for Event delivery for food orders" in text
    assert "scenario_context" not in answer
    assert answer["entities"]
    # The unselected payment-retry option stays visible, after the selected choice.
    assert "Payment retry delivery" in text
    assert text.index("Event delivery for food orders") < text.index("Payment retry delivery")
    assert answer["evidence"]
    assert answer["grounded"] is bool(answer["claims"])


def _kafka_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DecisionService:
    root = tmp_path / "food-delivery"
    _bootstrap(root)
    monkeypatch.setattr("switchplinth.service.qdrant_search", lambda *args, **kwargs: [])
    return DecisionService(root, tmp_path / ".food-delivery-decision-cache")


def test_why_answer_punctuates_rationale_before_ungrounded_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _kafka_service(tmp_path, monkeypatch)
    for claim_path in (service.repository.root / ".decision/claims").glob("*.yaml"):
        claim_path.unlink()

    answer = service.search("Why Kafka?")

    assert answer["grounded"] is False
    assert "operations. No current claim supports this why answer" in answer["answer"]


def _decision_by_title(service: DecisionService, title: str) -> dict:
    return next(record for record in service.repository.records("decisions") if record["title"] == title)


def _option_by_title(decision: dict, title: str) -> dict:
    return next(option for option in decision["options"] if option["title"] == title)


def _entity_added_by(option: dict) -> str:
    return next(operation["entity"]["id"] for operation in option["delta"]["operations"] if operation["op"] == "add_entity")


def _alias_record(alias_id: str, entity_id: str, name: str, evidence: list[str]) -> dict:
    return {"schema_version": "decision/v1", "record_type": "alias", "id": alias_id, "entity_id": entity_id, "name": name, "epistemic_state": "inferred", "confidence": 0.9, "evidence": evidence}


def test_selected_exact_match_outranks_unselected_exact_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _kafka_service(tmp_path, monkeypatch)
    retry_kafka = _option_by_title(_decision_by_title(service, "Payment retry delivery"), "Apache Kafka")
    retry_queue_id = _entity_added_by(retry_kafka)
    service.repository.save("aliases", _alias_record("alias-retry-queue-kafka", retry_queue_id, "Kafka", retry_kafka["evidence"][:1]))
    # The active Apache Kafka entity also carries the exact alias "kafka".
    assert any(alias["name"].casefold() == "kafka" and alias["entity_id"] != retry_queue_id for alias in service.repository.records("aliases"))

    answer = service.search("Why Kafka?")

    assert "scenario_context" not in answer
    assert "Apache Kafka was selected for Event delivery for food orders" in answer["answer"]
    assert "Unselected alternatives: Apache Kafka for Payment retry delivery." in answer["answer"]


def test_unselected_exact_match_wins_when_selected_match_is_only_a_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _kafka_service(tmp_path, monkeypatch)
    retry_kafka = _option_by_title(_decision_by_title(service, "Payment retry delivery"), "Apache Kafka")
    retry_queue_id = _entity_added_by(retry_kafka)
    for alias in service.repository.records("aliases"):
        if alias["name"].casefold() == "kafka":
            (service.repository.root / ".decision/aliases" / f"{alias['id']}.yaml").unlink()
    service.repository.save("aliases", _alias_record("alias-retry-queue-kafka", retry_queue_id, "Kafka", retry_kafka["evidence"][:1]))

    answer = service.search("Why Kafka?")

    assert retry_queue_id in {entity["id"] for entity in answer["scenario_context"]["inactive_entities"]}


def test_why_unselected_option_is_grounded_by_its_own_indexed_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _kafka_service(tmp_path, monkeypatch)
    monkeypatch.setattr("switchplinth.service.qdrant_rebuild", lambda *args, **kwargs: "indexed test vectors")
    service.rebuild_indexes()
    event_delivery = _decision_by_title(service, "Event delivery for food orders")
    kafka_evidence = {
        evidence_id
        for decision in service.repository.records("decisions")
        for option in decision["options"]
        if option["title"] == "Apache Kafka"
        for evidence_id in option["evidence"] or decision["evidence"]
    }

    answer = service.search("Why Kafka?", {event_delivery["id"]: _option_by_title(event_delivery, "Amazon SQS")["id"]})

    assert "scenario_context" in answer
    assert answer["claims"] == []
    assert answer["evidence"]
    assert {item["id"] for item in answer["evidence"]} <= kafka_evidence
    assert all(item["context"] == "decision_option" for item in answer["evidence"])
    assert answer["grounded"] is True
    assert "No current claim supports" not in answer["answer"]

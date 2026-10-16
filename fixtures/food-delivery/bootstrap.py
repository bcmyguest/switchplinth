"""Create a deterministic local graph from the fictional food-delivery Markdown."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import patch

from switchplinth.domain import stable_id
from switchplinth.service import DecisionService


def bootstrap(root: Path) -> dict[str, Any]:
    """Copy the docs and run deterministic mock extraction with source-backed resources."""
    root = root.resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Refusing to bootstrap into a non-empty directory: {root}")
    root.mkdir(parents=True, exist_ok=True)
    docs = Path(__file__).parent / "docs"
    for source in docs.rglob("*.md"):
        destination = root / source.relative_to(docs)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    service = DecisionService(root, root.parent / f".{root.name}-decision-cache")
    reporting_id = "datastore-postgres-reporting"
    # `scan()` uses deterministic mock extraction; no model connection is configured.
    with patch("switchplinth.service.qdrant_rebuild", return_value="disabled for offline fixture bootstrap"):
        scan = service.scan()
    order_service_id = stable_id("entity", "order service")
    kafka_id = stable_id("entity", "apache kafka")
    evidence = service.repository.records("evidence")
    reporting_evidence = next((item for item in evidence if "separately provisioned PostgreSQL instance" in item["text"]), None)
    if reporting_evidence is None:
        raise RuntimeError("Mock scan did not retain the reporting database source passage.")

    reporting_entity = next((item for item in service.repository.records("entities") if item["id"] == reporting_id), None)
    if reporting_entity is None or reporting_entity["evidence"] != [reporting_evidence["id"]]:
        raise AssertionError("Mock scan did not extract the source-backed Analytics reporting PostgreSQL instance.")
    graph = service.graph_json()
    entities = graph["entities"]
    if sum(entity["id"] == order_service_id for entity in entities) != 1:
        raise AssertionError("Expected one logical Order Service node from deterministic extraction.")
    if sum(entity["id"] == kafka_id for entity in entities) != 1:
        raise AssertionError("Expected one logical Kafka node from deterministic extraction.")
    if not any(entity["id"] == "datastore-postgres-reporting" and entity["name"] == "Analytics reporting PostgreSQL" for entity in entities):
        raise AssertionError("Expected the separately contextualized Analytics reporting PostgreSQL instance.")
    order_database = next((entity for entity in entities if entity["name"] == "Order database (PostgreSQL)"), None)
    if order_database is None:
        raise AssertionError("Expected the Order Service's source-backed PostgreSQL database resource.")
    if graph["identity_groups"]:
        raise AssertionError("The bootstrap should not seed identity groups.")
    if scan["candidate_decision_count"] != 7 or len(graph["decisions"]) != 7:
        raise AssertionError("Expected transport, order placement/data, payment, menu, dispatch, and availability decisions.")
    return {"scan": scan, "graph": graph, "order_service_id": order_service_id, "kafka_id": kafka_id, "postgres_ids": sorted(("datastore-postgres-reporting", order_database["id"]))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="new or empty repository directory to create")
    args = parser.parse_args()
    result = bootstrap(args.root)
    print(f"Bootstrapped {args.root.resolve()}")
    print(f"Documents: {result['scan']['document_count']}; decisions: {result['scan']['candidate_decision_count']}")
    print(f"Order Service node: {result['order_service_id']}; Kafka node: {result['kafka_id']}")
    print(f"Distinct PostgreSQL records: {', '.join(result['postgres_ids'])}")


if __name__ == "__main__":
    main()

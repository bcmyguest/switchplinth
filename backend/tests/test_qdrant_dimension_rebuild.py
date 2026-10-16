"""A rebuild recreates the namespaced Qdrant collection when the embedding dimension changes."""

from __future__ import annotations

from typing import Any

import pytest
import qdrant_client

from switchplinth.domain import Evidence
from switchplinth.store import qdrant_rebuild

COLLECTION = "decision_passages_test"


class FakeQdrantClient:
    collections: dict[str, dict[str, Any]] = {}

    def __init__(self, url: str, timeout: int) -> None:
        self.url = url

    def collection_exists(self, name: str) -> bool:
        return name in self.collections

    def delete_collection(self, name: str) -> None:
        del self.collections[name]

    def create_collection(self, collection_name: str, vectors_config: Any) -> None:
        self.collections[collection_name] = {"size": vectors_config.size, "points": []}

    def upsert(self, collection_name: str, points: list[Any], wait: bool) -> None:
        assert wait
        collection = self.collections[collection_name]
        if any(len(point.vector) != collection["size"] for point in points):
            raise ValueError("vector dimension mismatch")
        collection["points"].extend(points)


def test_rebuild_recreates_collection_when_embedding_dimension_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeQdrantClient.collections = {COLLECTION: {"size": 256, "points": [object()] * 4}}
    monkeypatch.setattr(qdrant_client, "QdrantClient", FakeQdrantClient)
    passage = Evidence("evidence-1", "docs/a.md", ["A"], "hash-1", text="Amazon SQS queues dispatch jobs.")

    status = qdrant_rebuild("http://qdrant:6333", [passage], None, COLLECTION, embedder=lambda text: [0.1] * 768)

    assert status == f"indexed 1 passage vectors in {COLLECTION}"
    assert FakeQdrantClient.collections[COLLECTION]["size"] == 768
    assert len(FakeQdrantClient.collections[COLLECTION]["points"]) == 1

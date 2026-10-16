"""Disposable SQLite document and graph projection index."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Callable, Protocol

from switchplinth.domain import Evidence, Graph

VECTOR_SIZE = 256
QDRANT_COLLECTION = "decision_passages"
INDEX_VERSION = 1


def hashed_embedding(text: str, dimensions: int = VECTOR_SIZE) -> list[float]:
    """Small deterministic local vectorizer for offline indexing and fallback retrieval."""
    vector = [0.0] * dimensions
    tokens = [token.casefold() for token in text.split() if token.isalnum()]
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        position = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[position] += sign
    magnitude = sum(value * value for value in vector) ** 0.5
    return [value / magnitude for value in vector] if magnitude else vector


class SearchIndex:
    def __init__(self, path: Path):
        self.path = path
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS passages (id TEXT PRIMARY KEY, path TEXT, heading TEXT, text TEXT, metadata TEXT)")
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5(id UNINDEXED, text, tokenize='unicode61')")
            db.execute("CREATE TABLE IF NOT EXISTS index_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def rebuild(self, passages: list[Evidence], graph: Graph) -> None:
        self._ensure_schema()
        with self.connect() as db:
            db.execute("DELETE FROM passages")
            db.execute("DELETE FROM passage_fts")
            for passage in passages:
                metadata = {"entity_ids": [entity_id for entity_id, entity in graph.entities.items() if entity.name.casefold() in passage.text.casefold()], "evidence_id": passage.id}
                db.execute("INSERT INTO passages VALUES (?, ?, ?, ?, ?)", (passage.id, passage.source_path, " / ".join(passage.heading_path), passage.text, json.dumps(metadata)))
                db.execute("INSERT INTO passage_fts VALUES (?, ?)", (passage.id, passage.text))
            db.execute("INSERT OR REPLACE INTO index_metadata VALUES ('index_version', ?)", (str(INDEX_VERSION),))

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        terms = [word for word in query.split() if word.isalnum()]
        if not terms:
            return []
        expression = " OR ".join(f'"{term}"' for term in terms)
        with self.connect() as db:
            rows = db.execute("SELECT p.*, bm25(passage_fts) AS rank FROM passage_fts JOIN passages p USING(id) WHERE passage_fts MATCH ? ORDER BY rank LIMIT ?", (expression, limit)).fetchall()
        return [dict(row) | {"metadata": json.loads(row["metadata"])} for row in rows]


class VectorIndex(Protocol):
    """Disposable passage-vector index for one repository, rebuilt from canonical evidence.

    `rebuild` replaces the whole index and returns a status string; a status
    starting with ``unavailable:`` reports failure and it never raises.
    `search` returns payloads (`evidence_id`, `path`, `heading`, `text`,
    `entity_ids`, `score`) best-first and sets `diagnostics` ``status`` to
    ``supported``, ``unsupported``, or ``error`` with a ``detail``; it returns
    ``[]`` instead of raising. A ``None`` embedder means `hashed_embedding`.
    `kind` names the adapter (``qdrant`` or ``local``) in index status reports.
    """

    kind: str

    def rebuild(self, passages: list[Evidence], graph: Graph, embedder: Callable[[str], list[float]] | None) -> str: ...

    def search(self, query: str, embedder: Callable[[str], list[float]] | None, diagnostics: dict[str, str]) -> list[dict[str, Any]]: ...


def passage_vector_points(passages: list[Evidence], graph: Graph | None, embedder: Callable[[str], list[float]] | None) -> tuple[int, list[tuple[list[float], dict[str, Any]]]]:
    """Embed passages and build the `VectorIndex` payloads shared by every adapter.

    Returns the vector dimension and one ``(vector, payload)`` pair per passage.
    Raises ``ValueError`` when vectors are empty or differ in dimension.
    """
    vectorize = embedder or hashed_embedding
    vectors = [vectorize(passage.text) for passage in passages]
    dimensions = len(vectors[0]) if vectors else VECTOR_SIZE
    if dimensions == 0 or any(len(vector) != dimensions for vector in vectors):
        raise ValueError("Embedding vectors must have one consistent non-zero dimension.")
    entity_names = {entity_id: entity.name for entity_id, entity in (graph.entities.items() if graph else [])}
    points = []
    for passage, vector in zip(passages, vectors, strict=True):
        related = [entity_id for entity_id, name in entity_names.items() if name.casefold() in passage.text.casefold()]
        points.append((vector, {"evidence_id": passage.id, "path": passage.source_path, "heading": " / ".join(passage.heading_path), "text": passage.text, "entity_ids": related}))
    return dimensions, points


def qdrant_rebuild(url: str, passages: list[Evidence], graph: Graph | None = None, collection: str = QDRANT_COLLECTION, embedder: Callable[[str], list[float]] | None = None) -> str:
    """Recreate the derived Qdrant collection with a matching local or provider vectorizer."""
    try:
        from qdrant_client import QdrantClient, models
        dimensions, vector_points = passage_vector_points(passages, graph, embedder)
        client = QdrantClient(url=url, timeout=2)
        if client.collection_exists(collection):
            client.delete_collection(collection)
        client.create_collection(collection_name=collection, vectors_config=models.VectorParams(size=dimensions, distance=models.Distance.COSINE))
        points = [models.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, payload["evidence_id"])), vector=vector, payload=payload) for vector, payload in vector_points]
        if points:
            client.upsert(collection_name=collection, points=points, wait=True)
        return f"indexed {len(points)} passage vectors in {collection}"
    except Exception as exc:
        return f"unavailable: {type(exc).__name__}: {exc}"


def qdrant_search(url: str, query: str, limit: int = 8, collection: str = QDRANT_COLLECTION, embedder: Callable[[str], list[float]] | None = None, diagnostics: dict[str, str] | None = None) -> list[dict[str, Any]]:
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=url, timeout=2)
        if not client.collection_exists(collection):
            if diagnostics is not None:
                diagnostics.update(status="unsupported", detail=f"Qdrant collection {collection!r} does not exist; run discovery scan.")
            return []
        vector = (embedder or hashed_embedding)(query)
        response = client.query_points(collection_name=collection, query=vector, limit=limit, with_payload=True)
        if diagnostics is not None:
            diagnostics.update(status="supported", detail="Query embedding matched the indexed vector backend.")
        return [dict(point.payload or {}) | {"score": point.score} for point in response.points]
    except Exception as exc:
        if diagnostics is not None:
            diagnostics.update(status="error", detail=f"{type(exc).__name__}: {exc}")
        return []

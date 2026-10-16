"""In-process vector index that stands in for Qdrant when no Qdrant service runs."""

from __future__ import annotations

from typing import Any, Callable

from switchplinth.domain import Evidence, Graph
from switchplinth.store import hashed_embedding, passage_vector_points

SEARCH_LIMIT = 8


class LocalVectorIndex:
    """`VectorIndex` adapter over in-memory vectors, for running without a Qdrant service.

    A ``None`` embedder uses the same deterministic hashed vectors as the
    Qdrant adapter. The index is disposable and lives only in this process.
    """

    kind = "local"

    def __init__(self) -> None:
        self.points: list[tuple[list[float], dict[str, Any]]] | None = None

    def rebuild(self, passages: list[Evidence], graph: Graph, embedder: Callable[[str], list[float]] | None) -> str:
        try:
            _, points = passage_vector_points(passages, graph, embedder)
            self.points = points
            return f"indexed {len(points)} passage vectors in the local in-process index"
        except Exception as exc:
            return f"unavailable: {type(exc).__name__}: {exc}"

    def search(self, query: str, embedder: Callable[[str], list[float]] | None, diagnostics: dict[str, str]) -> list[dict[str, Any]]:
        if self.points is None:
            diagnostics.update(status="unsupported", detail="The local vector index is not built.")
            return []
        try:
            vector = (embedder or hashed_embedding)(query)
        except Exception as exc:
            diagnostics.update(status="error", detail=f"{type(exc).__name__}: {exc}")
            return []
        scored = [(_cosine(vector, point_vector), payload) for point_vector, payload in self.points if len(point_vector) == len(vector)]
        scored.sort(key=lambda item: item[0], reverse=True)
        diagnostics.update(status="supported", detail="Query embedding matched the local in-process vector index.")
        return [dict(payload) | {"score": score} for score, payload in scored[:SEARCH_LIMIT] if score > 0]


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    magnitude = (sum(a * a for a in left) ** 0.5) * (sum(b * b for b in right) ** 0.5)
    return dot / magnitude if magnitude else 0.0


"""Record-read caching and punctuated lexical search."""

from pathlib import Path

import pytest

from switchplinth.domain import DomainError, Evidence, Graph
from switchplinth.repository import PortableRepository
from switchplinth.store import SearchIndex


def _entity(entity_id: str, name: str) -> dict:
    return {"schema_version": "decision/v1", "record_type": "entity", "id": entity_id, "kind": "service", "name": name, "epistemic_state": "asserted"}


def test_records_reflect_saved_and_hand_edited_files(tmp_path: Path) -> None:
    repository = PortableRepository(tmp_path)
    repository.bootstrap_overlay()
    repository.save("entities", _entity("entity-a", "Orders"))
    first = repository.records("entities")
    first[0]["name"] = "mutated by a caller"

    assert repository.records("entities")[0]["name"] == "Orders"

    repository.save("entities", _entity("entity-a", "Order Service"))
    assert repository.records("entities")[0]["name"] == "Order Service"

    path = tmp_path / ".decision" / "entities" / "entity-a.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("Order Service", "Order API"), encoding="utf-8")
    assert repository.records("entities")[0]["name"] == "Order API"

    path.write_text(path.read_text(encoding="utf-8").replace("kind: service", "kind: [service]"), encoding="utf-8")
    with pytest.raises(DomainError):
        repository.records("entities")


def test_lexical_search_keeps_terms_followed_by_punctuation(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "index.sqlite3")
    passage = Evidence("ev-1", "docs/events.md", ["Events", "Decision"], "0" * 64, text="Replay and per-order ordering matter.")
    index.rebuild([passage], Graph())

    hits = index.search("Which decisions mention replay?")

    assert [hit["id"] for hit in hits] == ["ev-1"]

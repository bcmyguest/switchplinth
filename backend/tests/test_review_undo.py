"""Human review log and append-only undo."""

from pathlib import Path
import shutil

import pytest
from fastapi import HTTPException

from switchplinth.api import ExactIdentityReviewRequest, create_app
from switchplinth.repository import PortableRepository, passages, source_identity
from switchplinth.service import DecisionService


def make_repository(root: Path) -> tuple[PortableRepository, DecisionService, dict[str, object]]:
    root.mkdir(parents=True, exist_ok=True)
    repository = PortableRepository(root)
    service = DecisionService(root, root.parent / "cache")
    for entity_id, name in (("a", "Alpha"), ("b", "Beta")):
        repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": entity_id, "kind": "service", "name": name})
    source = root / "docs/source.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("Alpha uses Beta, also called Bee.", encoding="utf-8")
    passage = passages(source, root)[0]
    evidence = {
        "schema_version": "decision/v1", "record_type": "evidence", "id": passage.id,
        "source": source_identity(source, root),
        "location": {"heading_path": passage.heading_path, "normalized_passage_sha256": passage.passage_sha256, "context_before": passage.context_before, "context_after": passage.context_after, "display_line": passage.display_line},
        "text": passage.text, "state": "current",
    }
    repository.save("evidence", evidence)
    repository.save("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": "inferred-uses", "subject": "a", "predicate": "uses", "object": "b", "epistemic_state": "inferred", "confidence": 0.8, "evidence": [evidence["id"]]})
    repository.save("aliases", {"schema_version": "decision/v1", "record_type": "alias", "id": "inferred-bee", "entity_id": "b", "name": "Bee", "epistemic_state": "inferred", "confidence": 0.7, "evidence": [evidence["id"]]})
    return repository, service, evidence


def route(app, path: str):
    return next(item for item in app.routes if getattr(item, "path", None) == path)


def effective_claim_ids(service: DecisionService) -> set[str]:
    return {claim["id"] for claim in service.graph_json()["claims"]}


def test_confirm_then_undo_restores_original_inference(tmp_path: Path) -> None:
    repository, service, _ = make_repository(tmp_path / "repo")
    original = (repository.overlay / "claims/inferred-uses.yaml").read_bytes()
    confirmed = service.review_claim("inferred-uses", "confirmed")
    assert effective_claim_ids(service) == {confirmed["id"]}

    result = route(create_app(service), "/api/v1/reviews/{record_id}/undo").endpoint(confirmed["id"])

    assert result["undone_record_id"] == confirmed["id"]
    assert result["restored_record_ids"] == ["inferred-uses"]
    assert result["already_undone"] is False and result["kind"] == "claim"
    undo = result["undo"]
    assert undo["undoes"] == confirmed["id"] and undo["supersedes"] == [confirmed["id"]]
    assert undo["reviewed_claim"] == "inferred-uses" and undo["reviewer"] == "human" and undo["reviewed_at"]
    assert effective_claim_ids(service) == {"inferred-uses"}
    assert [relationship["claim_id"] for relationship in service.graph_json()["relationships"]] == ["inferred-uses"]
    # Append-only: the inference and the undone judgment stay on disk unchanged.
    assert (repository.overlay / "claims/inferred-uses.yaml").read_bytes() == original
    assert {record["id"] for record in repository.records("claims")} == {"inferred-uses", confirmed["id"], undo["id"]}

    log = route(create_app(service), "/api/v1/reviews").endpoint()["entries"]
    assert [entry["id"] for entry in log] == [undo["id"], confirmed["id"]]
    assert log[0]["judgment"] == "undo" and log[0]["undoable"] is False and log[0]["effective"] is False
    assert log[1] | {"reviewed_at": None} == log[1] | {
        "kind": "claim", "judgment": "confirmed", "summary": "Alpha uses Beta", "reviewed_record": "inferred-uses",
        "subject": {"subject": {"id": "a", "name": "Alpha"}, "predicate": "uses", "object": {"id": "b", "name": "Beta"}},
        "undone_by": undo["id"], "effective": False, "undoable": False, "reviewed_at": None,
    }


def test_correct_then_undo_restores_prior_human_judgment(tmp_path: Path) -> None:
    repository, service, _ = make_repository(tmp_path / "repo")
    confirmed = service.review_claim("inferred-uses", "confirmed")
    corrected = service.correct_claim(confirmed["id"], "b", "calls", "a")
    assert effective_claim_ids(service) == {corrected["id"]}
    entries = {entry["id"]: entry for entry in service.review_log()["entries"]}
    assert entries[corrected["id"]]["judgment"] == "corrected" and entries[corrected["id"]]["undoable"] is True
    assert entries[confirmed["id"]]["undoable"] is False and entries[confirmed["id"]]["superseded_by"] == corrected["id"]

    result = service.undo_review(corrected["id"])

    assert result["restored_record_ids"] == [confirmed["id"]]
    assert effective_claim_ids(service) == {confirmed["id"]}
    assert [(item["from"], item["kind"], item["to"]) for item in service.graph_json()["relationships"]] == [("a", "uses", "b")]
    # A second undo walks back to the original inference.
    service.undo_review(confirmed["id"])
    assert effective_claim_ids(service) == {"inferred-uses"}


def test_undo_rejects_non_head_records_and_is_idempotent(tmp_path: Path) -> None:
    repository, service, _ = make_repository(tmp_path / "repo")
    undo_route = route(create_app(service), "/api/v1/reviews/{record_id}/undo")
    confirmed = service.review_claim("inferred-uses", "confirmed")
    rejected = service.review_claim(confirmed["id"], "rejected")

    for record_id, message in ((confirmed["id"], rejected["id"]), ("inferred-uses", "not a human review")):
        with pytest.raises(HTTPException) as conflict:
            undo_route.endpoint(record_id)
        assert conflict.value.status_code == 409
        assert message in conflict.value.detail
    with pytest.raises(HTTPException) as missing:
        undo_route.endpoint("missing-record")
    assert missing.value.status_code == 404

    first = undo_route.endpoint(rejected["id"])
    file_count = len(list((repository.overlay / "claims").glob("*.yaml")))
    repeated = undo_route.endpoint(rejected["id"])
    assert repeated["already_undone"] is True and repeated["undo"] == first["undo"]
    assert len(list((repository.overlay / "claims").glob("*.yaml"))) == file_count
    assert effective_claim_ids(service) == {confirmed["id"]}
    with pytest.raises(HTTPException) as undo_of_undo:
        undo_route.endpoint(first["undo"]["id"])
    assert undo_of_undo.value.status_code == 409

    # Redo is a fresh review that supersedes the undone judgment and its undo.
    redo = service.review_claim("inferred-uses", "rejected")
    assert {rejected["id"], first["undo"]["id"]} <= set(redo["supersedes"])
    assert effective_claim_ids(service) == set()


def test_alias_review_undo_restores_inferred_alias(tmp_path: Path) -> None:
    _, service, _ = make_repository(tmp_path / "repo")
    rejected = service.review_alias("inferred-bee", "rejected")
    assert [alias["id"] for alias in service.graph_json()["aliases"]] == []
    entry = next(item for item in service.review_log()["entries"] if item["id"] == rejected["id"])
    assert entry["kind"] == "alias" and entry["summary"] == "“Bee” → Beta" and entry["undoable"] is True

    result = service.undo_review(rejected["id"])

    assert result["kind"] == "alias" and result["restored_record_ids"] == ["inferred-bee"]
    assert [alias["id"] for alias in service.graph_json()["aliases"]] == ["inferred-bee"]


def test_identity_review_undo_and_redo(tmp_path: Path) -> None:
    repository, service, _ = make_repository(tmp_path / "repo")
    repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "c", "kind": "service", "name": "alpha"})
    app = create_app(service)
    review = route(app, "/api/v1/identity-candidates/review")
    request = ExactIdentityReviewRequest(entity_ids=["a", "c"], epistemic_state="confirmed")
    confirmed = review.endpoint(request)["claim"]
    assert service.graph_json()["identity_groups"] == [{"entity_ids": ["a", "c"]}]

    result = route(app, "/api/v1/reviews/{record_id}/undo").endpoint(confirmed["id"])

    assert result["kind"] == "identity" and result["restored_record_ids"] == []
    graph = service.graph_json()
    assert graph["identity_groups"] == []
    assert [item["source"] for item in graph["identity_suggestions"]] == ["exact_name"]
    assert "claim_id" not in graph["identity_suggestions"][0]
    entry = next(item for item in service.review_log()["entries"] if item["id"] == confirmed["id"])
    assert entry["kind"] == "identity" and entry["summary"] == "Alpha is the same entity as alpha" and entry["undone_by"] == result["undo"]["id"]

    redo = review.endpoint(request)["claim"]
    assert redo["id"] != confirmed["id"] and redo["reviewed_claim"] == confirmed["id"]
    assert service.graph_json()["identity_groups"] == [{"entity_ids": ["a", "c"]}]
    service.undo_review(redo["id"])
    assert service.graph_json()["identity_groups"] == []


def test_review_log_and_undo_state_rebuild_from_canonical_files(tmp_path: Path) -> None:
    repository, service, _ = make_repository(tmp_path / "repo")
    confirmed = service.review_claim("inferred-uses", "confirmed")
    corrected = service.correct_claim(confirmed["id"], "a", "calls", "b")
    service.undo_review(corrected["id"])
    service.review_alias("inferred-bee", "confirmed")
    log = service.review_log()
    graph = service.graph_json()

    copy_root = tmp_path / "copy"
    shutil.copytree(tmp_path / "repo", copy_root)
    rebuilt = DecisionService(copy_root, tmp_path / "fresh-cache")

    assert rebuilt.review_log() == log
    assert {claim["id"] for claim in rebuilt.graph_json()["claims"]} == {claim["id"] for claim in graph["claims"]} == {confirmed["id"]}
    assert [entry["judgment"] for entry in log["entries"]] == ["confirmed", "undo", "corrected", "confirmed"]


def test_review_metadata_is_validated_by_bundled_schema(tmp_path: Path) -> None:
    from switchplinth.domain import DomainError

    repository, service, _ = make_repository(tmp_path / "repo")
    confirmed = service.review_claim("inferred-uses", "confirmed")
    with pytest.raises(DomainError, match="reviewed_at"):
        repository.save("claims", {**confirmed, "id": "bad-time", "reviewed_at": "yesterday"})
    repository.save("claims", {**confirmed, "id": "dangling-undo", "undoes": "missing", "supersedes": []})
    with pytest.raises(DomainError, match="must supersede"):
        repository.records("claims")



def assert_only_head_undoable(service: DecisionService, root_id: str, head_id: str) -> None:
    entries = {entry["id"]: entry for entry in service.review_log()["entries"]}
    assert entries[root_id]["undoable"] is False and entries[root_id]["effective"] is False
    assert entries[root_id]["superseded_by"] == head_id
    assert entries[head_id]["undoable"] is True and entries[head_id]["effective"] is True
    with pytest.raises(HTTPException) as conflict:
        route(create_app(service), "/api/v1/reviews/{record_id}/undo").endpoint(root_id)
    assert conflict.value.status_code == 409 and head_id in conflict.value.detail


def assert_both_undoable(service: DecisionService, *record_ids: str) -> None:
    entries = {entry["id"]: entry for entry in service.review_log()["entries"]}
    assert all(entries[record_id]["undoable"] is True and entries[record_id]["effective"] is True for record_id in record_ids)


def identity_repository(root: Path) -> tuple[PortableRepository, DecisionService, dict[str, object], dict[str, object]]:
    repository, service, _ = make_repository(root)
    repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "c", "kind": "service", "name": "alpha"})
    confirmed = service.review_exact_identity_candidate(["a", "c"], "confirmed")["claim"]
    assert "reviewed_claim" not in confirmed
    return repository, service, confirmed, service.review_claim(confirmed["id"], "rejected")


def test_review_of_root_identity_judgment_supersedes_root(tmp_path: Path) -> None:
    _, service, confirmed, rejected = identity_repository(tmp_path / "repo")
    assert rejected["supersedes"] == [confirmed["id"]]
    assert service.graph_json()["identity_conflicts"] == []

    assert_only_head_undoable(service, confirmed["id"], rejected["id"])

    result = service.undo_review(rejected["id"])
    assert result["restored_record_ids"] == [confirmed["id"]]
    graph = service.graph_json()
    assert graph["identity_groups"] == [{"entity_ids": ["a", "c"]}] and graph["identity_conflicts"] == []
    assert {entry["id"]: entry for entry in service.review_log()["entries"]}[confirmed["id"]]["undoable"] is True


@pytest.mark.parametrize("undo_root", [False, True], ids=["undo-head", "undo-root"])
def test_legacy_unsuperseded_identity_pair_is_conflict_undoable_either_way(tmp_path: Path, undo_root: bool) -> None:
    repository, service, confirmed, rejected = identity_repository(tmp_path / "repo")
    # Records written before the fix omitted the root; both judgments stay active.
    repository.save("claims", {**rejected, "supersedes": []})
    assert len(service.graph_json()["identity_conflicts"]) == 1
    assert_both_undoable(service, confirmed["id"], rejected["id"])

    service.undo_review(confirmed["id"] if undo_root else rejected["id"])

    graph = service.graph_json()
    assert graph["identity_conflicts"] == []
    assert graph["identity_groups"] == ([] if undo_root else [{"entity_ids": ["a", "c"]}])


def alias_repository(root: Path) -> tuple[PortableRepository, DecisionService, dict[str, object], dict[str, object]]:
    repository, service, evidence = make_repository(root)
    human_root = {"schema_version": "decision/v1", "record_type": "alias", "id": "human-root-bee", "entity_id": "b", "name": "Bee", "epistemic_state": "asserted", "confidence": 1.0, "evidence": [evidence["id"]], "reviewer": "human", "reviewed_at": "2026-01-01T00:00:00.000000+00:00"}
    repository.save("aliases", human_root)
    return repository, service, human_root, service.review_alias(human_root["id"], "rejected")


def test_review_of_root_human_alias_supersedes_root(tmp_path: Path) -> None:
    _, service, human_root, rejected = alias_repository(tmp_path / "repo")
    assert rejected["supersedes"] == [human_root["id"]]

    assert_only_head_undoable(service, human_root["id"], rejected["id"])

    result = service.undo_review(rejected["id"])
    assert result["kind"] == "alias" and result["restored_record_ids"] == [human_root["id"]]


def effective_log_ids(service: DecisionService) -> set[str]:
    return {entry["id"] for entry in service.review_log()["entries"] if entry["effective"]}


def test_legacy_unsuperseded_alias_pair_follows_domain_choice(tmp_path: Path) -> None:
    repository, service, human_root, rejected = alias_repository(tmp_path / "repo")
    # Legacy record: both judgments are unsuperseded; the domain keeps one per alias.
    repository.save("aliases", {**rejected, "supersedes": []})
    assert [alias["id"] for alias in service.graph_json()["aliases"]] == [human_root["id"]]
    assert effective_log_ids(service) == {human_root["id"]}
    loser = next(entry for entry in service.review_log()["entries"] if entry["id"] == rejected["id"])
    assert loser["undoable"] is False and loser["superseded_by"] is None and human_root["id"] in loser["undo_blocked_reason"]
    with pytest.raises(HTTPException) as conflict:
        route(create_app(service), "/api/v1/reviews/{record_id}/undo").endpoint(rejected["id"])
    assert conflict.value.status_code == 409 and human_root["id"] in conflict.value.detail

    service.undo_review(human_root["id"])
    assert [alias["id"] for alias in service.graph_json()["aliases"]] == []
    assert effective_log_ids(service) == {rejected["id"]}

    service.undo_review(rejected["id"])
    assert [alias["id"] for alias in service.graph_json()["aliases"]] == ["inferred-bee"]
    assert effective_log_ids(service) == set()


def test_legacy_unsuperseded_claim_pair_follows_domain_choice(tmp_path: Path) -> None:
    repository, service, evidence = make_repository(tmp_path / "repo")
    human_root = {"schema_version": "decision/v1", "record_type": "claim", "id": "human-root-uses", "subject": "a", "predicate": "uses", "object": "b", "epistemic_state": "confirmed", "confidence": 1.0, "evidence": [evidence["id"]], "reviewer": "human", "reviewed_at": "2026-01-01T00:00:00.000000+00:00"}
    repository.save("claims", human_root)
    rejected = service.review_claim(human_root["id"], "rejected")
    assert rejected["supersedes"] == [human_root["id"]]
    repository.save("claims", {**rejected, "supersedes": []})
    assert effective_claim_ids(service) == {human_root["id"]}
    assert effective_log_ids(service) == {human_root["id"]}
    with pytest.raises(HTTPException) as conflict:
        route(create_app(service), "/api/v1/reviews/{record_id}/undo").endpoint(rejected["id"])
    assert conflict.value.status_code == 409

    service.undo_review(human_root["id"])
    assert effective_claim_ids(service) == set()
    assert effective_log_ids(service) == {rejected["id"]}

    service.undo_review(rejected["id"])
    assert effective_claim_ids(service) == {"inferred-uses"}
    assert effective_log_ids(service) == set()


def test_hand_edited_supersedes_cycle_is_consistent(tmp_path: Path) -> None:
    repository, service, _ = make_repository(tmp_path / "repo")
    first = service.review_claim("inferred-uses", "confirmed")
    second = service.review_claim("inferred-uses", "asserted")
    repository.save("claims", {**first, "supersedes": [second["id"]]})
    assert second["supersedes"] == [first["id"]]

    entries = {entry["id"]: entry for entry in service.review_log()["entries"]}
    assert effective_claim_ids(service) == {"inferred-uses"}
    assert effective_log_ids(service) == set()
    assert entries[first["id"]]["undoable"] is False and entries[second["id"]]["undoable"] is False

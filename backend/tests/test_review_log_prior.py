"""Review-log entries describe the prior state each judgment replaced."""

from pathlib import Path

from switchplinth.api import ExactIdentityReviewRequest, create_app
from switchplinth.repository import PortableRepository, passages, source_identity
from switchplinth.service import DecisionService


def make_repository(root: Path) -> tuple[PortableRepository, DecisionService]:
    root.mkdir(parents=True, exist_ok=True)
    repository = PortableRepository(root)
    service = DecisionService(root, root.parent / "cache")
    for entity_id, name in (("a", "Alpha"), ("b", "Beta"), ("c", "alpha")):
        repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": entity_id, "kind": "service", "name": name})
    source = root / "docs/source.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("Alpha uses Beta, also called Bee.", encoding="utf-8")
    passage = passages(source, root)[0]
    repository.save("evidence", {
        "schema_version": "decision/v1", "record_type": "evidence", "id": passage.id,
        "source": source_identity(source, root),
        "location": {"heading_path": passage.heading_path, "normalized_passage_sha256": passage.passage_sha256, "context_before": passage.context_before, "context_after": passage.context_after, "display_line": passage.display_line},
        "text": passage.text, "state": "current",
    })
    repository.save("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": "inferred-uses", "subject": "a", "predicate": "uses", "object": "b", "epistemic_state": "inferred", "confidence": 0.8, "evidence": [passage.id]})
    repository.save("aliases", {"schema_version": "decision/v1", "record_type": "alias", "id": "inferred-bee", "entity_id": "b", "name": "Bee", "epistemic_state": "inferred", "confidence": 0.7, "evidence": [passage.id]})
    return repository, service


def log_entries(service: DecisionService) -> dict[str, dict[str, object]]:
    app = create_app(service)
    endpoint = next(item for item in app.routes if getattr(item, "path", None) == "/api/v1/reviews").endpoint
    return {entry["id"]: entry for entry in endpoint()["entries"]}


INFERRED_USES = {"id": "inferred-uses", "epistemic_state": "inferred", "judgment": None, "summary": "Alpha uses Beta", "subject": {"subject": {"id": "a", "name": "Alpha"}, "predicate": "uses", "object": {"id": "b", "name": "Beta"}}}
INFERRED_BEE = {"id": "inferred-bee", "epistemic_state": "inferred", "judgment": None, "summary": "“Bee” → Beta", "subject": {"alias": "Bee", "entity": {"id": "b", "name": "Beta"}}}


def test_claim_confirm_undo_reconfirm_reports_prior_state(tmp_path: Path) -> None:
    repository, service = make_repository(tmp_path / "repo")
    original = (repository.overlay / "claims/inferred-uses.yaml").read_bytes()

    confirmed = service.review_claim("inferred-uses", "confirmed")
    assert log_entries(service)[confirmed["id"]]["prior"] == [INFERRED_USES]

    undo = service.undo_review(confirmed["id"])["undo"]
    entries = log_entries(service)
    assert entries[undo["id"]]["prior"] == [{**INFERRED_USES, "id": confirmed["id"], "epistemic_state": "confirmed", "judgment": "confirmed"}]
    assert entries[confirmed["id"]]["prior"] == [INFERRED_USES]

    redo = service.review_claim("inferred-uses", "confirmed")
    prior = {item["id"]: item for item in log_entries(service)[redo["id"]]["prior"]}
    assert list(prior) == ["inferred-uses", *redo["supersedes"]]
    assert prior["inferred-uses"] == INFERRED_USES
    assert prior[confirmed["id"]]["judgment"] == "confirmed" and prior[undo["id"]]["judgment"] == "undo"
    assert (repository.overlay / "claims/inferred-uses.yaml").read_bytes() == original


def test_claim_correction_prior_keeps_original_inferred_text(tmp_path: Path) -> None:
    repository, service = make_repository(tmp_path / "repo")
    original = (repository.overlay / "claims/inferred-uses.yaml").read_bytes()

    corrected = service.correct_claim("inferred-uses", "b", "calls", "a")

    entry = log_entries(service)[corrected["id"]]
    assert entry["judgment"] == "corrected" and entry["summary"] == "Beta calls Alpha"
    assert entry["prior"] == [INFERRED_USES]
    service.undo_review(corrected["id"])
    assert {claim["id"] for claim in service.graph_json()["claims"]} == {"inferred-uses"}
    assert (repository.overlay / "claims/inferred-uses.yaml").read_bytes() == original


def test_alias_confirm_undo_reconfirm_and_correction_report_prior_state(tmp_path: Path) -> None:
    repository, service = make_repository(tmp_path / "repo")
    original = (repository.overlay / "aliases/inferred-bee.yaml").read_bytes()

    confirmed = service.review_alias("inferred-bee", "confirmed")
    assert log_entries(service)[confirmed["id"]]["prior"] == [INFERRED_BEE]
    undo = service.undo_review(confirmed["id"])["undo"]
    assert log_entries(service)[undo["id"]]["prior"] == [{**INFERRED_BEE, "id": confirmed["id"], "epistemic_state": "confirmed", "judgment": "confirmed"}]
    redo = service.review_alias("inferred-bee", "confirmed")
    assert [item["id"] for item in log_entries(service)[redo["id"]]["prior"]] == ["inferred-bee", *redo["supersedes"]]
    assert [alias["id"] for alias in service.graph_json()["aliases"]] == [redo["id"]]

    corrected = service.correct_alias(redo["id"], "Bea", "b")
    entry = log_entries(service)[corrected["id"]]
    assert entry["summary"] == "“Bea” → Beta"
    assert {item["id"]: item["summary"] for item in entry["prior"]}["inferred-bee"] == "“Bee” → Beta"
    assert (repository.overlay / "aliases/inferred-bee.yaml").read_bytes() == original


def test_identity_confirm_undo_reconfirm_reports_prior_state(tmp_path: Path) -> None:
    repository, service = make_repository(tmp_path / "repo")
    original = {path.name: path.read_bytes() for path in (repository.overlay / "claims").glob("*.yaml")}
    app = create_app(service)
    review = next(item for item in app.routes if getattr(item, "path", None) == "/api/v1/identity-candidates/review").endpoint
    request = ExactIdentityReviewRequest(entity_ids=["a", "c"], epistemic_state="confirmed")

    confirmed = review(request)["claim"]
    # A first exact-name judgment replaces no record: the prior state was an unreviewed suggestion.
    assert log_entries(service)[confirmed["id"]]["prior"] == []

    undo = service.undo_review(confirmed["id"])["undo"]
    assert log_entries(service)[undo["id"]]["prior"] == [{
        "id": confirmed["id"], "epistemic_state": "confirmed", "judgment": "confirmed", "summary": "Alpha is the same entity as alpha",
        "subject": {"subject": {"id": "a", "name": "Alpha"}, "predicate": "same_entity_as", "object": {"id": "c", "name": "alpha"}},
    }]

    redo = review(request)["claim"]
    prior = log_entries(service)[redo["id"]]["prior"]
    assert [item["id"] for item in prior] == list(redo["supersedes"]) and confirmed["id"] in redo["supersedes"]
    assert service.graph_json()["identity_groups"] == [{"entity_ids": ["a", "c"]}]
    assert all((repository.overlay / "claims" / name).read_bytes() == data for name, data in original.items())


def test_prior_reports_unresolved_reference_without_failing(tmp_path: Path) -> None:
    repository, service = make_repository(tmp_path / "repo")
    confirmed = service.review_claim("inferred-uses", "confirmed")
    record = next(item for item in repository.records("claims") if item["id"] == confirmed["id"])
    repository.save("claims", {**record, "id": "human-claim-dangling", "supersedes": ["missing-record"]})

    assert log_entries(service)["human-claim-dangling"]["prior"] == [INFERRED_USES, {"id": "missing-record", "epistemic_state": None, "judgment": None, "summary": None, "subject": None}]


def test_prior_effective_names_the_judgment_effective_before_each_entry(tmp_path: Path) -> None:
    repository, service = make_repository(tmp_path / "repo")
    original = (repository.overlay / "claims/inferred-uses.yaml").read_bytes()
    a = service.review_claim("inferred-uses", "confirmed")
    b = service.review_claim("inferred-uses", "rejected")
    undo_b = service.undo_review(b["id"])["undo"]
    c = service.review_claim("inferred-uses", "rejected")
    d = service.correct_claim(c["id"], "b", "calls", "a")

    entries = log_entries(service)
    assert entries[a["id"]]["prior_effective"] == ["inferred-uses"]
    assert entries[b["id"]]["prior_effective"] == [a["id"]]
    assert entries[undo_b["id"]]["prior_effective"] == [b["id"]]
    assert entries[undo_b["id"]]["judgment"] == "undo"
    assert entries[c["id"]]["prior_effective"] == [a["id"]]
    assert entries[d["id"]]["prior_effective"] == [c["id"]]
    assert (repository.overlay / "claims/inferred-uses.yaml").read_bytes() == original


def test_prior_effective_for_alias_and_identity_chains(tmp_path: Path) -> None:
    _, service = make_repository(tmp_path / "repo")
    alias = service.review_alias("inferred-bee", "confirmed")
    alias_undo = service.undo_review(alias["id"])["undo"]
    alias_redo = service.review_alias("inferred-bee", "confirmed")
    identity = service.review_exact_identity_candidate(["a", "c"], "confirmed")["claim"]
    identity_undo = service.undo_review(identity["id"])["undo"]
    identity_redo = service.review_exact_identity_candidate(["a", "c"], "confirmed")["claim"]

    entries = log_entries(service)
    assert entries[alias["id"]]["prior_effective"] == ["inferred-bee"]
    assert entries[alias_undo["id"]]["prior_effective"] == [alias["id"]]
    assert entries[alias_redo["id"]]["prior_effective"] == ["inferred-bee"]
    # No record precedes a first exact-name judgment or its redo after undo: the prior state is an unreviewed suggestion.
    assert entries[identity["id"]]["prior_effective"] == []
    assert entries[identity_undo["id"]]["prior_effective"] == [identity["id"]]
    assert entries[identity_redo["id"]]["prior_effective"] == []

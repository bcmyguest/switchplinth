"""Architecture log reasons derived from cited source passages."""

from pathlib import Path
import importlib.util
import time

from switchplinth.api import create_app
from switchplinth.decision_log import SourceStatement, decision_log_reasons, decision_reasons
from switchplinth.domain import Decision, Evidence, Option
from switchplinth.service import DecisionService

ROOT = Path(__file__).parents[2]


def passage(evidence_id: str, heading: str, text: str, source_path: str = "docs/a.md", title: str = "Doc", state: str = "current") -> Evidence:
    return Evidence(id=evidence_id, source_path=source_path, heading_path=[title, heading], passage_sha256="0" * 64, text=text, state=state)


def decision(*options: Option, selected: str = "chosen", evidence: list[str] | None = None) -> Decision:
    return Decision(id="d", title="Doc", status="accepted", context="", selected_option=selected, options=list(options), evidence=evidence or ["ev-decision"])


def option(option_id: str, *evidence: str) -> Option:
    return Option(id=option_id, title=option_id, rationale="", delta={}, evidence=list(evidence))


def test_rejection_reason_is_clause_after_but() -> None:
    alternative = passage("ev-alt", "Alternative: queue", "Queue X could carry events, but replay would require extra support. Other text.")
    reasons = decision_reasons(decision(option("chosen", "ev-decision"), option("alt", "ev-alt")), [alternative])
    assert reasons.rejection_reasons == {"alt": SourceStatement(text="replay would require extra support.", evidence_id="ev-alt")}


def test_rejection_reason_falls_back_to_limitation_sentence() -> None:
    alternative = passage("ev-alt", "Alternative: pool", "A fixed pool is simple. The team would still need to coordinate restarts. It is cheap.")
    reasons = decision_reasons(decision(option("chosen"), option("alt", "ev-alt")), [alternative])
    assert reasons.rejection_reasons["alt"] == SourceStatement(text="The team would still need to coordinate restarts.", evidence_id="ev-alt")


def test_rejection_reason_absent_when_source_states_none() -> None:
    alternative = passage("ev-alt", "Alternative: pool", "A fixed pool is simple and cheap.")
    reasons = decision_reasons(decision(option("chosen"), option("alt", "ev-alt")), [alternative])
    assert reasons.rejection_reasons == {}


def test_selected_option_never_gets_rejection_reason() -> None:
    chosen = passage("ev-decision", "Decision", "We chose Kafka, but it costs more.")
    reasons = decision_reasons(decision(option("chosen", "ev-decision")), [chosen])
    assert reasons.rejection_reasons == {}


def test_alternative_heading_passage_preferred_over_other_citations() -> None:
    actor = passage("ev-actor", "Context", "The service runs jobs, but it is busy.")
    alternative = passage("ev-alt", "Considered alternative: cron", "Cron could run jobs, but failures would be silent.")
    reasons = decision_reasons(decision(option("chosen"), option("alt", "ev-actor", "ev-alt")), [actor, alternative])
    assert reasons.rejection_reasons["alt"] == SourceStatement(text="failures would be silent.", evidence_id="ev-alt")


def test_consequences_from_same_document_section_only() -> None:
    anchor = passage("ev-decision", "Decision", "We chose Kafka.")
    own = passage("ev-cons", "Consequences", "The team operates Kafka. Lag is monitored.")
    other_doc = passage("ev-other", "Consequences", "Unrelated doc outcome.", source_path="docs/b.md")
    stale = passage("ev-stale", "Consequences", "Old outcome.", state="stale")
    reasons = decision_reasons(decision(option("chosen", "ev-decision")), [anchor, own, other_doc, stale])
    assert reasons.consequences == [SourceStatement("The team operates Kafka.", "ev-cons"), SourceStatement("Lag is monitored.", "ev-cons")]


def test_missing_consequences_section_yields_empty_list() -> None:
    anchor = passage("ev-decision", "Decision", "We chose Kafka.")
    assert decision_reasons(decision(option("chosen", "ev-decision")), [anchor]).consequences == []


FOOD_DELIVERY_REASONS = {
    "Event delivery for food orders": ("Amazon SQS", "replaying a selected range of historical order events would require additional application support.", 2),
    "Payment retry delivery": ("Apache Kafka", "the payment retry consumer would need separate retry and dead-letter handling.", 2),
    "Courier dispatch runtime": ("Fixed worker pool backed by Amazon SQS", "The team would still need to coordinate worker restarts and capacity changes separately.", 2),
    "Order placement and restaurant reservation": ("Wait for reservation during checkout", "a slow restaurant would hold the customer request open and make retries harder to distinguish from new orders.", 2),
    "RFC: courier and restaurant availability": ("Reporting PostgreSQL database queries", "it is not the source for live courier assignment.", 2),
    "RFC: durable order data": ("Redis", "It does not replace the durable order database or the transactional boundary for checkout.", 0),
    "RFC: restaurant and menu reads": ("PostgreSQL", "peak browse traffic would compete with transactional order writes.", 2),
}


def bootstrap_food_delivery(root: Path) -> dict:
    module_path = ROOT / "fixtures/food-delivery/bootstrap.py"
    spec = importlib.util.spec_from_file_location("food_delivery_bootstrap_log", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.bootstrap(root)


def decision_bytes(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted((root / ".decision").rglob("*")) if path.is_file()}


def test_food_delivery_log_reasons_match_sources(tmp_path: Path) -> None:
    graph = bootstrap_food_delivery(tmp_path / "food-delivery")["graph"]
    passages = {item["id"]: item for item in graph["evidence"]}
    assert {item["title"] for item in graph["decisions"]} == set(FOOD_DELIVERY_REASONS)
    for rendered in graph["decisions"]:
        alternative_title, reason, consequence_count = FOOD_DELIVERY_REASONS[rendered["title"]]
        derived = rendered["derived"]
        selected = next(item for item in rendered["options"] if item["id"] == rendered["selected_option"])
        assert selected["rationale"].strip()
        (alternative,) = [item for item in rendered["options"] if item["id"] != rendered["selected_option"]]
        assert alternative["title"] == alternative_title
        assert set(derived["rejection_reasons"]) == {alternative["id"]}
        assert derived["rejection_reasons"][alternative["id"]]["text"] == reason
        assert len(derived["consequences"]) == consequence_count
        for statement in [*derived["consequences"], *derived["rejection_reasons"].values()]:
            assert statement["text"] in passages[statement["evidence_id"]]["text"]
            assert passages[statement["evidence_id"]].get("state", "current") == "current"
    assert sum(bool(item["derived"]["consequences"]) for item in graph["decisions"]) == 6


def test_decisions_endpoint_exposes_derived_without_writing(tmp_path: Path) -> None:
    root = tmp_path / "food-delivery"
    bootstrap_food_delivery(root)
    service = DecisionService(root, tmp_path / "cache")
    before = decision_bytes(root)
    app = create_app(service)
    decisions = next(item for item in app.routes if getattr(item, "path", None) == "/api/v1/decisions").endpoint()
    assert len(decisions) == 7
    assert all(set(item["derived"]) == {"consequences", "rejection_reasons"} for item in decisions)
    assert decision_bytes(root) == before


def test_undecided_decision_has_no_rejection_reasons() -> None:
    first = passage("ev-a", "Alternative: A", "A works, but it is costly.")
    second = passage("ev-b", "Alternative: B", "B works, but it would be slower.")
    undecided = decision(option("a", "ev-a"), option("b", "ev-b"), selected=None)
    assert decision_reasons(undecided, [first, second]).rejection_reasons == {}


def test_fallback_never_uses_a_passage_the_selected_option_or_decision_cites() -> None:
    shared = passage("ev-decision", "Decision", "We chose Kafka over SQS, but Kafka costs more to operate.")
    reasons = decision_reasons(decision(option("chosen", "ev-decision"), option("alt", "ev-decision")), [shared])
    assert reasons.rejection_reasons == {}
    selected_only = passage("ev-shared", "Context", "Both queues work, but SQS would lack replay.")
    reasons = decision_reasons(decision(option("chosen", "ev-shared"), option("alt", "ev-shared")), [passage("ev-decision", "Decision", "We chose Kafka."), selected_only])
    assert reasons.rejection_reasons == {}


def test_favorable_contrast_clause_is_not_a_rejection_reason() -> None:
    alternative = passage("ev-alt", "Alternative: B", "B is slow, but cheap.")
    assert decision_reasons(decision(option("chosen"), option("alt", "ev-alt")), [alternative]).rejection_reasons == {}


def test_consequences_belong_to_the_decisions_own_section() -> None:
    first = Evidence("ev-d1", "docs/a.md", ["Doc", "Queue choice", "Decision"], "0" * 64, text="We chose Kafka.")
    first_consequence = Evidence("ev-c1", "docs/a.md", ["Doc", "Queue choice", "Consequences"], "0" * 64, text="Kafka is operated.")
    second_consequence = Evidence("ev-c2", "docs/a.md", ["Doc", "Cache choice", "Consequences"], "0" * 64, text="Redis is operated.")
    reasons = decision_reasons(decision(option("chosen", "ev-d1"), evidence=["ev-d1"]), [first, first_consequence, second_consequence])
    assert reasons.consequences == [SourceStatement("Kafka is operated.", "ev-c1")]


def test_batch_derivation_scales_linearly_with_decisions_and_passages() -> None:
    passages = [passage(f"ev-{index}", "Consequences" if index % 10 == 0 else "Alternative: x", "X works, but it would be slower.", source_path=f"docs/{index // 10}.md") for index in range(20000)]
    decisions = [Decision(f"d-{index}", "D", "accepted", "", "chosen", [option("chosen"), option("alt", f"ev-{index * 10 + 1}")], [f"ev-{index * 10 + 1}"]) for index in range(2000)]
    started = time.perf_counter()
    derived = decision_log_reasons(decisions, passages)
    elapsed = time.perf_counter() - started
    assert len(derived) == 2000
    assert derived["d-7"].rejection_reasons["alt"].evidence_id == "ev-71"
    assert elapsed < 0.5, f"2000 decisions x 20000 passages took {elapsed:.2f}s; the quadratic version measured 2.01s"

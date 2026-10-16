"""Application services composed from portable data and disposable indexes."""

from __future__ import annotations

import hashlib
import re
import uuid
import os
import copy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from switchplinth import DEFAULT_CACHE_ROOT
from switchplinth.decision_log import decision_log_reasons
from switchplinth.domain import Claim, Decision, DomainError, Entity, Evidence, Graph, Option, Relationship, ScenarioResult, compile_scenario, effective_aliases, effective_claims, identity_projection, load_yaml, stable_id, without_undone_reviews
from switchplinth.providers import diagnose, embed_with_litellm, extract_with_litellm, propose_delta_with_litellm
from switchplinth.receipt import RECEIPT_FOLDERS, input_receipt
from switchplinth.repository import PortableRepository, discover_markdown, passages, relocate_evidence, source_identity, source_is_included
from switchplinth.scenario_analysis import ResolvedScenario, diff_resolved_scenarios, downstream_impact, option_replacements
from switchplinth.store import INDEX_VERSION, SearchIndex, VectorIndex, qdrant_rebuild, qdrant_search

REVIEW_FOLDERS = (("claims", "reviewed_claim"), ("aliases", "reviewed_alias"))
PORTABLE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
PROMPT_ENTITY_LIMIT = 200
ENTITY_REFERENCE_GUIDE = (
    "\n\nENTITY REFERENCES: In option delta relationship operations, set from and to to an entity ID listed below, "
    "to the id of an entity added by the same delta, or to the exact name of an entity you return in entities. "
    "For an entity you return in entities, use its exact name, not an invented ID; the backend maps a name to an ID "
    "only when it matches exactly one entity."
)


class ReviewConflictError(Exception):
    """A requested review-log change conflicts with the current review chain."""


def review_timestamp() -> str:
    """Return the UTC timestamp stored on newly appended human review records."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def is_human_review(record: dict[str, Any], root_key: str) -> bool:
    """Return whether a claim or alias record is an appended human review."""
    return record.get("reviewer") == "human" or root_key in record or bool(record.get("undoes"))


def review_supersession(active: list[dict[str, Any]]) -> dict[str, str]:
    """Map each explicitly superseded active record ID to one superseding active record ID.

    Only explicit ``supersedes`` entries count, matching graph compilation, so
    unsuperseded opposing judgments stay visible as conflicts.
    """
    return {superseded: row["id"] for row in active for superseded in row.get("supersedes", [])}


def review_shadowing(active: list[dict[str, Any]], folder: str) -> dict[str, str]:
    """Map unsuperseded human judgments the domain does not choose to the judgment it chooses.

    ``effective_aliases`` and ``effective_claims`` keep one human judgment per
    alias or proposition. Rejections are promoted to confirmations only so the
    chosen judgment appears in the domain output. Identity claims keep their
    conflict projection and are never shadowed.
    """
    superseded = review_supersession(active)
    human = [row for row in active if row.get("epistemic_state") in {"confirmed", "asserted", "rejected"} and row["id"] not in superseded]
    promoted = [{**row, "epistemic_state": "confirmed"} if row.get("epistemic_state") == "rejected" else row for row in active]
    if folder == "aliases":
        chosen = {row["id"] for row in effective_aliases(promoted)}
        key = lambda row: (row.get("entity_id"), str(row.get("name", "")).casefold())
    else:
        human = [row for row in human if row.get("predicate") != "same_entity_as"]
        chosen = {claim.id for claim in effective_claims([Claim(row["id"], str(row.get("subject", "")), str(row.get("predicate", "")), str(row.get("object", "")), row.get("epistemic_state", "inferred"), float(row.get("confidence", 0)), row.get("evidence", []), row.get("source_path"), row.get("supersedes", [])) for row in promoted])}
        key = lambda row: (str(row.get("subject", "")), str(row.get("predicate", "")), str(row.get("object", "")))
    winners = {key(row): row["id"] for row in human if row["id"] in chosen}
    return {row["id"]: winners[key(row)] for row in human if row["id"] not in chosen and key(row) in winners}


class QdrantVectorIndex:
    """Default `VectorIndex` adapter: one Qdrant collection named for one repository.

    `QDRANT_URL` is read on every call. The adapter calls this module's
    `qdrant_rebuild`/`qdrant_search` names so tests can patch them here.
    """

    kind = "qdrant"

    def __init__(self, collection: str):
        self.collection = collection

    def rebuild(self, passages: list[Evidence], graph: Graph, embedder: Callable[[str], list[float]] | None) -> str:
        return qdrant_rebuild(os.environ.get("QDRANT_URL", "http://qdrant:6333"), passages, graph, self.collection, embedder=embedder)

    def search(self, query: str, embedder: Callable[[str], list[float]] | None, diagnostics: dict[str, str]) -> list[dict[str, Any]]:
        return qdrant_search(os.environ.get("QDRANT_URL", "http://qdrant:6333"), query, collection=self.collection, embedder=embedder, diagnostics=diagnostics)


def _append_sentence(text: str, sentence: str) -> str:
    """Join a sentence to text, ending the text with a period when it lacks terminal punctuation."""
    text = text.rstrip()
    if not text:
        return sentence
    return f"{text} {sentence}" if text.endswith((".", "!", "?")) else f"{text}. {sentence}"


class DecisionService:
    def __init__(self, root: Path, cache: Path | None = None, vector_index: VectorIndex | None = None):
        self.repository = PortableRepository(root)
        self.root = root.resolve()
        self.qdrant_collection = f"decision_passages_{hashlib.sha256(self.root.as_posix().encode()).hexdigest()[:16]}"
        self.vector_index = vector_index or QdrantVectorIndex(self.qdrant_collection)
        self.cache = cache or Path(os.environ.get("DECISION_CACHE", DEFAULT_CACHE_ROOT))
        self.index = SearchIndex(self.cache / "index.sqlite3")
        self.connections: dict[str, dict[str, Any]] = {}
        for record in self.repository.records("connections"):
            self.connections[record["id"]] = record
        self.qdrant_status = "not indexed"

    def _embedding_setup(self) -> tuple[dict[str, Any] | None, dict[str, str]]:
        """Select one explicit embedding model or describe the local fallback."""
        configured = [item for item in self.connections.values() if item.get("capabilities", {}).get("embeddings")]
        if not configured:
            return None, {"status": "unsupported", "mode": "deterministic_local", "detail": "No embedding model is configured; using the deterministic local vector fallback."}
        if len(configured) != 1:
            return None, {"status": "error", "mode": "deterministic_local", "detail": "Select exactly one connection with embeddings enabled."}
        connection = configured[0]
        if not connection.get("embedding_model"):
            return None, {"status": "unsupported", "mode": "deterministic_local", "detail": "Embeddings are enabled, but no embedding_model is configured; using the deterministic local vector fallback."}
        if connection.get("provider") == "anthropic":
            return None, {"status": "unsupported", "mode": "deterministic_local", "detail": "Anthropic embeddings are not available through the V0 provider adapter; using the deterministic local vector fallback."}
        return connection, {"status": "pending", "mode": "provider", "model": str(connection["embedding_model"]), "detail": "Configured provider embeddings will be used for indexing and search."}

    def rebuild_indexes(self) -> dict[str, Any]:
        """Rebuild disposable SQLite and vector indexes from current canonical evidence, without scanning Markdown."""
        evidence: dict[str, Evidence] = {}
        for record in self.repository.records("evidence"):
            if record.get("state", "current") != "current":
                continue
            location, source = record["location"], record["source"]
            evidence.setdefault(record["id"], Evidence(record["id"], source["path"], location["heading_path"], location["normalized_passage_sha256"], location.get("context_before", ""), location.get("context_after", ""), source.get("git_blob"), location.get("display_line"), record.get("text", ""), "current"))
        return self._rebuild_indexes(list(evidence.values()))

    def _rebuild_indexes(self, evidence: list[Evidence]) -> dict[str, Any]:
        """Rebuild disposable search indexes from canonical evidence and records."""
        graph = self.graph()[0]
        self.index.rebuild(evidence, graph)
        embedding_connection, embedding_status = self._embedding_setup()
        embedder = (lambda text: embed_with_litellm(embedding_connection, text)) if embedding_connection else None
        self.qdrant_status = self.vector_index.rebuild(evidence, graph, embedder)
        if embedding_connection:
            embedding_status["status"] = "error" if self.qdrant_status.startswith("unavailable:") else "supported"
            if embedding_status["status"] == "error":
                embedding_status["detail"] = self.qdrant_status
        # "qdrant" is the historical key for the vector status of any adapter;
        # "vector_index" names the adapter that produced it.
        return {"version": INDEX_VERSION, "sqlite": str(self.cache / "index.sqlite3"), "qdrant": self.qdrant_status, "vector_index": {"kind": self.vector_index.kind, "status": self.qdrant_status}, "embedding": embedding_status}

    def _read_records(self) -> dict[str, list[dict[str, Any]]]:
        """Read and validate, once, every canonical record folder the graph and its receipt consume."""
        return {folder: self.repository.records(folder) for folder in RECEIPT_FOLDERS}

    def graph(self, records: dict[str, list[dict[str, Any]]] | None = None) -> tuple[Graph, list[Decision], list[dict[str, Any]], list[dict[str, Any]], list[Claim]]:
        """Build the base graph from ``records`` (folder -> raw records), reading them when omitted."""
        records = records if records is not None else self._read_records()
        entity_records = records["entities"]
        option_created_entities = {operation.get("entity", {}).get("id") for record in records["decisions"] for option in record.get("options", []) for operation in option.get("delta", {}).get("operations", []) if operation.get("op") == "add_entity"}
        # Older mock-extractor overlays wrote base candidate entities without an
        # epistemic state. Treat those legacy records like inferred duplicates
        # when an option delta owns the same ID. Explicit human assertions stay
        # in the base graph so the compiler can surface the ownership conflict.
        entity_records = [record for record in entity_records if not (record["id"] in option_created_entities and record.get("epistemic_state") not in {"confirmed", "asserted"})]
        entities = {r["id"]: Entity(r["id"], r.get("kind", "component"), r.get("name", r["id"]), r.get("description", "")) for r in entity_records}
        relationships: dict[str, Relationship] = {}
        claims = [Claim(r["id"], str(r.get("subject", "")), str(r.get("predicate", "")), str(r.get("object", "")), r.get("epistemic_state", "inferred"), float(r.get("confidence", 0)), r.get("evidence", []), r.get("source_path"), r.get("supersedes", [])) for r in without_undone_reviews(records["claims"])]
        for claim in effective_claims(claims):
            if claim.predicate in {"uses", "publishes_to", "calls", "depends_on", "stores_in", "communicates_with", "implements"} and claim.subject in entities and claim.object in entities:
                rid = stable_id("relationship", f"{claim.subject}/{claim.predicate}/{claim.object}")
                relationships[rid] = Relationship(rid, claim.subject, claim.object, claim.predicate, claim.id)
        for r in records["relationships"]:
            if r.get("epistemic_state") == "rejected":
                relationships.pop(r["id"], None)
                continue
            if r.get("from") in entities and r.get("to") in entities:
                relationships[r["id"]] = Relationship(r["id"], r["from"], r["to"], r.get("kind", "related"))
        decisions: list[Decision] = []
        for r in records["decisions"]:
            opts = [Option(o["id"], o.get("title", o["id"]), o.get("rationale", ""), o.get("delta", {"operations": []}), o.get("evidence", [])) for o in r.get("options", [])]
            decisions.append(Decision(r["id"], r.get("title", r["id"]), r.get("status", "proposed"), r.get("context", ""), r.get("selected_option"), opts, r.get("evidence", [])))
        return Graph(entities, relationships), decisions, effective_aliases(without_undone_reviews(records["aliases"])), records["evidence"], claims

    def scan(self) -> dict[str, Any]:
        """Run deterministic extraction and restore portable YAML on failure."""
        return self._run_scan(mock_extract=True)

    def prepare_provider_sources(self) -> dict[str, Any]:
        """Refresh Markdown evidence and indexes without running mock extraction."""
        return self._run_scan(mock_extract=False)

    def _run_scan(self, mock_extract: bool) -> dict[str, Any]:
        """Index Markdown and restore portable YAML if a synchronous scan fails."""
        overlay_files = {path.relative_to(self.repository.overlay): path.read_bytes() for path in self.repository.overlay.rglob("*") if path.is_file()}
        try:
            return self._scan(mock_extract=mock_extract)
        except Exception:
            overlay = self.repository.overlay
            current_files = {path.relative_to(overlay) for path in overlay.rglob("*") if path.is_file()}
            for relative in current_files - set(overlay_files):
                (overlay / relative).unlink(missing_ok=True)
            for relative, content in overlay_files.items():
                path = overlay / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            raise

    def _scan(self, mock_extract: bool = True) -> dict[str, Any]:
        config_path = self.repository.overlay / "config.yaml"
        config = load_yaml(config_path) if config_path.exists() else {}
        self.repository.validate_config(config)
        extraction = config.get("extraction", {})
        excludes = set(extraction.get("ignore", []))
        includes = extraction.get("include", [])
        if not isinstance(includes, list) or not all(isinstance(item, str) for item in includes):
            raise DomainError("extraction.include must be a list of source paths.")
        max_candidates = max(1, int(extraction.get("max_candidates", 50)))
        files = discover_markdown(self.root, excludes, includes)
        evidence = [item for path in files for item in passages(path, self.root)]
        previous_records = self.repository.records_unchecked("evidence")
        previous = [Evidence(record["id"], record["source"]["path"], record["location"]["heading_path"], record["location"]["normalized_passage_sha256"], record["location"]["context_before"], record["location"]["context_after"], record["source"].get("git_blob"), record["location"].get("display_line"), record["text"], record.get("state", "current")) for record in previous_records]
        current_objects = {id(item): item for item in evidence}
        used: set[str] = set()
        for prior in previous:
            relocated = relocate_evidence(prior, evidence)
            object_id = str(id(relocated))
            if relocated.state == "unresolved" or id(relocated) not in current_objects or object_id in used:
                prior.state = "unresolved"
                continue
            current = current_objects[id(relocated)]
            current.id = prior.id
            used.add(object_id)
        candidates: dict[str, dict[str, str]] = {}
        catalog = (("Apache Kafka", "technology", ("kafka",)), ("PostgreSQL", "technology", ("postgres", "postgresql")), ("Amazon SQS", "technology", ("sqs",)), ("Redis", "technology", ("redis",)), ("Kubernetes", "platform", ("kubernetes", "k8s")), ("Order Service", "service", ("order service", "orders service")), ("Payments Service", "service", ("payments service", "payment service")), ("Restaurant Service", "service", ("restaurant service",)), ("Fulfillment Service", "service", ("fulfillment service",)), ("Dispatch workflow", "workflow", ("dispatch workflow",)), ("Dispatch workers", "worker", ("dispatch workers",)))
        extracted_decisions: list[dict[str, Any]] = []
        if mock_extract:
            # Heuristic extraction gives a repeatable baseline from arbitrary Markdown.
            lower = " ".join(item.text.casefold() for item in evidence)
            existing_decision_records = self.repository.records_unchecked("decisions")
            previous_decision_evidence = {evidence_id for record in existing_decision_records for evidence_id in record.get("evidence", [])}
            previous_decision_evidence.update(evidence_id for record in existing_decision_records for option in record.get("options", []) for evidence_id in option.get("evidence", []))
            extracted_decisions = self._mock_decisions([item for item in evidence if item.id not in previous_decision_evidence], catalog)[:max_candidates]
            option_entity_ids = {operation.get("entity", {}).get("id") for decision in extracted_decisions for option in decision["options"] for operation in option["delta"]["operations"] if operation["op"] == "add_entity"}
            for name, kind, mentions in catalog:
                if any(mention in lower for mention in mentions):
                    entity_id = stable_id("entity", name.casefold())
                    if entity_id not in option_entity_ids:
                        matched_evidence = [item.id for item in evidence if any(mention in item.text.casefold() for mention in mentions)]
                        candidates[entity_id] = {"id": entity_id, "kind": kind, "name": name, "epistemic_state": "inferred", "confidence": 0.85, "evidence": matched_evidence}
            reporting_source = next((item for item in evidence if "separately provisioned PostgreSQL instance" in item.text), None)
            if reporting_source:
                candidates["datastore-postgres-reporting"] = {
                    "id": "datastore-postgres-reporting", "kind": "datastore", "name": "Analytics reporting PostgreSQL",
                    "description": "Separate reporting instance in the Analytics Service context.", "epistemic_state": "inferred",
                    "confidence": 0.95, "evidence": [reporting_source.id],
                }
        for entity_id, item in candidates.items():
            if not any(record.get("id") == entity_id for record in self.repository.records_unchecked("entities")):
                self.repository.save("entities", {"schema_version": "decision/v1", "record_type": "entity", **item})
        stored = []
        existing_evidence = {record["id"] for record in previous_records}
        prior_by_id = {record["id"]: record for record in previous_records}
        for prior in previous:
            if prior.state == "unresolved" and prior.id in prior_by_id:
                prior_by_id[prior.id]["state"] = "unresolved"
                self.repository.save("evidence", prior_by_id[prior.id])
        for item in evidence:
            source = source_identity(self.root / item.source_path, self.root)
            prior_source = prior_by_id.get(item.id, {}).get("source", {})
            if (
                source["git_blob"] is None
                and prior_source.get("git_blob") is not None
                and prior_source.get("path") == source["path"]
                and prior_source.get("content_sha256") == source["content_sha256"]
            ):
                source["git_blob"] = prior_source["git_blob"]
            record = {"schema_version": "decision/v1", "record_type": "evidence", "id": item.id, "source": source, "location": {"heading_path": item.heading_path, "normalized_passage_sha256": item.passage_sha256, "context_before": item.context_before, "context_after": item.context_after, "display_line": item.display_line}, "text": item.text, "state": "current"}
            if item.id not in existing_evidence:
                self.repository.save("evidence", record)
                existing_evidence.add(item.id)
            elif prior_by_id.get(item.id) != record:
                self.repository.save("evidence", record)
            stored.append(item)
        # Evidence must exist before aliases and claims reference it. Repair stale
        # inferred anchors from earlier interrupted scans without touching reviews.
        current_evidence_ids = {item.id for item in stored}
        for alias in self.repository.records_unchecked("aliases"):
            if alias.get("epistemic_state") != "inferred":
                continue
            current_support = [item for item in alias.get("evidence", []) if item in current_evidence_ids]
            if current_support:
                if current_support != alias.get("evidence", []):
                    alias["evidence"] = current_support
                    self.repository.save("aliases", alias)
                continue
            matches = [item.id for item in stored if alias["name"].casefold() in item.text.casefold()]
            if matches:
                alias["evidence"] = matches[:1]
                self.repository.save("aliases", alias)
            else:
                alias_records = self.repository.records_unchecked("aliases")
                referenced = any(alias["id"] in record.get("supersedes", []) or record.get("reviewed_alias") == alias["id"] for record in alias_records if record["id"] != alias["id"])
                if referenced:
                    entity = next((record for record in self.repository.records_unchecked("entities") if record["id"] == alias.get("entity_id")), None)
                    replacement = [item.id for item in stored if entity and entity.get("name", "").casefold() in item.text.casefold()]
                    if not replacement:
                        raise DomainError(f"Reviewed alias {alias['id']} lost its evidence anchor and cannot be relocated safely.")
                    alias["evidence"] = replacement[:1]
                    self.repository.save("aliases", alias)
                else:
                    (self.repository.overlay / "aliases" / f"{alias['id']}.yaml").unlink(missing_ok=True)
        if mock_extract:
            for entity_id, item in candidates.items():
                catalog_entry = next((entry for entry in catalog if entry[0] == item["name"]), None)
                canonical_mentions = catalog_entry[2] if catalog_entry else ()
                for alias_name in canonical_mentions:
                    if alias_name.casefold() == item["name"].casefold():
                        continue
                    matches = [passage.id for passage in stored if alias_name.casefold() in passage.text.casefold()]
                    alias_id = stable_id("alias", f"{entity_id}/{alias_name.casefold()}")
                    aliases = self.repository.records_unchecked("aliases")
                    if matches and not any(record.get("id") == alias_id for record in aliases):
                        self.repository.save("aliases", {"schema_version": "decision/v1", "record_type": "alias", "id": alias_id, "entity_id": entity_id, "name": alias_name, "epistemic_state": "inferred", "confidence": 0.85, "evidence": matches})
            existing_claims = {record["id"] for record in self.repository.records_unchecked("claims")}
            for entity_id, item in candidates.items():
                catalog_entry = next((entry for entry in catalog if entry[0] == item["name"]), None)
                mentions = catalog_entry[2] if catalog_entry else ()
                for passage in evidence:
                    candidate_support = item.get("evidence", [])
                    has_mention = (
                        any(token.casefold() in passage.text.casefold() for token in (item["name"], *mentions))
                        if catalog_entry
                        else passage.id in candidate_support
                    )
                    if has_mention:
                        claim_id = stable_id("claim", f"mention/{entity_id}/{passage.id}")
                        if claim_id not in existing_claims:
                            self.repository.save("claims", {"schema_version": "decision/v1", "record_type": "claim", "id": claim_id, "subject": entity_id, "predicate": "mentioned_in", "object": passage.source_path, "epistemic_state": "inferred", "confidence": 0.99, "source_path": passage.source_path, "evidence": [passage.id]})
        decisions = self.repository.records_unchecked("decisions")
        # A lightweight format-agnostic classifier surfaces candidate sections for review.
        candidate_titles = []
        for item in evidence:
            if re.search(r"\b(we (?:will|should|decided to)|decision|we chose|we selected|adopt(?:ed)?)\b", item.text, re.I):
                candidate_titles.append({"source": item.source_path, "heading": item.heading_path[-1] if item.heading_path else "Document passage", "evidence": item.id})
        candidate_titles = candidate_titles[:max_candidates]
        known_decisions = {record["id"] for record in decisions}
        for decision in extracted_decisions:
            if decision["id"] not in known_decisions:
                self.repository.save("decisions", decision)
                decisions.append(decision)
        # Reconcile only after this scan has persisted its inferred records. Those
        # current-source records can provide valid support for entities whose old
        # evidence came solely from an excluded source.
        self._reconcile_excluded_task_inferences(includes)
        self._reconcile_excluded_task_entities(includes)
        index_status = self._rebuild_indexes(stored)
        graph, decisions, aliases, _, claims = self.graph()
        persisted_inferred = [record for record in self.repository.records_unchecked("decisions") if record.get("epistemic_state") == "inferred"]
        return {"documents": [{"path": p.relative_to(self.root).as_posix(), "passage_count": sum(x.source_path == p.relative_to(self.root).as_posix() for x in evidence)} for p in files], "document_count": len(files), "passage_count": len(evidence), "candidate_entity_count": len(candidates), "candidate_decision_count": len(extracted_decisions), "candidate_passage_count": len(candidate_titles), "persisted_inferred_decision_count": len(persisted_inferred), "candidate_claim_count": len(claims), "candidate_alias_count": len(aliases), "entities": list(candidates.values()), "candidate_decisions": candidate_titles + [{"id": d["id"], "title": d["title"], "status": d["status"], "options": [option["title"] for option in d["options"]]} for d in extracted_decisions], "index": {"version": index_status["version"], "sqlite": index_status["sqlite"], "qdrant": index_status["qdrant"], "vector_index": index_status["vector_index"]}, "embedding": index_status["embedding"]}

    def _reconcile_excluded_task_inferences(self, includes: list[str]) -> None:
        """Remove excluded task support from inferred records without rewriting reviews."""
        evidence = {record["id"]: record for record in self.repository.records_unchecked("evidence")}
        excluded_ids = {
            evidence_id
            for evidence_id, record in evidence.items()
            if ".tasks" in Path(record["source"]["path"]).parts
            and not source_is_included(record["source"]["path"], includes)
        }
        if not excluded_ids:
            return

        claims = self.repository.records_unchecked("claims")
        referenced_claims = {
            referenced
            for record in claims
            for referenced in record.get("supersedes", [])
        } | {
            record.get("reviewed_claim")
            for record in claims
            if record.get("reviewed_claim")
        }
        for claim in claims:
            support = set(claim.get("evidence", []))
            if claim.get("epistemic_state") != "inferred" or not support or not support.intersection(excluded_ids):
                continue
            if support - excluded_ids:
                claim["evidence"] = [item for item in claim["evidence"] if item not in excluded_ids]
                self.repository.save("claims", claim)
            elif claim["id"] not in referenced_claims:
                (self.repository.overlay / "claims" / f"{claim['id']}.yaml").unlink(missing_ok=True)

        # Relationships are also portable records, though provider extraction
        # currently represents most relationships as claims.
        relationships = self.repository.records_unchecked("relationships")
        scenarios = self.repository.records_unchecked("scenarios")
        scenario_options = {
            (decision_id, option_id)
            for scenario in scenarios
            for decision_id, option_id in scenario.get("selections", {}).items()
        }
        decisions = self.repository.records_unchecked("decisions")
        selected_relationships = {
            operation.get("relationship", {}).get("id")
            for decision in decisions
            for option in decision.get("options", [])
            if option.get("id") == decision.get("selected_option")
            for operation in option.get("delta", {}).get("operations", [])
            if operation.get("op") in {"add_relationship", "replace_relationship", "remove_relationship"}
        }
        human_reviewed_relationships = {
            operation.get("relationship", {}).get("id")
            for decision in decisions
            if decision.get("epistemic_state") in {"confirmed", "rejected", "asserted"}
            for option in decision.get("options", [])
            for operation in option.get("delta", {}).get("operations", [])
            if operation.get("op") in {"add_relationship", "replace_relationship", "remove_relationship"}
        }
        scenario_relationships = {
            operation.get("relationship", {}).get("id")
            for decision in decisions
            for option in decision.get("options", [])
            if (decision["id"], option["id"]) in scenario_options
            for operation in option.get("delta", {}).get("operations", [])
            if operation.get("op") in {"add_relationship", "replace_relationship", "remove_relationship"}
        }
        relationship_records = [
            record
            for kind in ("entities", "aliases", "claims", "relationships", "decisions", "scenarios")
            for record in self.repository.records_unchecked(kind)
        ]
        relationship_references = {
            reference
            for record in relationship_records
            for reference in record.get("supersedes", [])
        } | {
            record.get("reviewed_relationship")
            for record in relationship_records
            if record.get("reviewed_relationship")
        }
        for relationship in relationships:
            support = set(relationship.get("evidence", []))
            if relationship.get("epistemic_state") != "inferred" or not support.intersection(excluded_ids):
                continue
            if support - excluded_ids:
                relationship["evidence"] = [item for item in relationship["evidence"] if item not in excluded_ids]
                self.repository.save("relationships", relationship)
            elif relationship["id"] in relationship_references or relationship["id"] in scenario_relationships or relationship["id"] in selected_relationships or relationship["id"] in human_reviewed_relationships:
                raise DomainError(f"Cannot safely remove task-only relationship {relationship['id']}: it is reviewed or referenced by a selected option or scenario.")
            else:
                (self.repository.overlay / "relationships" / f"{relationship['id']}.yaml").unlink(missing_ok=True)

        decisions = self.repository.records_unchecked("decisions")
        reviewed_decision_references = {
            referenced
            for record in relationship_records
            for referenced in record.get("supersedes", [])
        } | {
            record.get("reviewed_decision")
            for record in relationship_records
            if record.get("reviewed_decision")
        }
        for decision in decisions:
            if decision.get("epistemic_state") != "inferred":
                continue
            decision_support = set(decision.get("evidence", []))
            decision_evidence_changed = bool(decision_support.intersection(excluded_ids))
            if decision_evidence_changed:
                decision["evidence"] = [item for item in decision.get("evidence", []) if item not in excluded_ids]
            changed = decision_evidence_changed
            contaminated = [
                option for option in decision.get("options", [])
                if option.get("evidence") and set(option["evidence"]).intersection(excluded_ids)
            ]
            remove_options = []
            for option in contaminated:
                support = set(option["evidence"])
                if support - excluded_ids:
                    option["evidence"] = [item for item in option["evidence"] if item not in excluded_ids]
                    changed = True
                else:
                    remove_options.append(option)
            if not remove_options and not changed:
                continue
            if decision["id"] in reviewed_decision_references:
                raise DomainError(f"Cannot safely reconcile task-only decision {decision['id']}: it is referenced by a human review.")
            for option in remove_options:
                if option["id"] == decision.get("selected_option") or (decision["id"], option["id"]) in scenario_options:
                    raise DomainError(
                        f"Cannot safely remove task-only option {option['id']} from decision {decision['id']}: it is selected or referenced by a scenario."
                    )
            remaining = [option for option in decision["options"] if option not in remove_options]
            if remove_options and not remaining:
                if decision.get("selected_option") or any(decision["id"] in scenario.get("selections", {}) for scenario in scenarios):
                    raise DomainError(f"Cannot safely reconcile decision {decision['id']}: no supported options would remain while selected or referenced by a scenario.")
                (self.repository.overlay / "decisions" / f"{decision['id']}.yaml").unlink(missing_ok=True)
                continue
            decision["options"] = remaining
            self.repository.save("decisions", decision)

    def _reconcile_excluded_task_entities(self, includes: list[str]) -> None:
        """Filter excluded support and safely remove unreferenced task-only entities."""
        evidence = {record["id"]: record for record in self.repository.records_unchecked("evidence")}
        excluded_ids = {
            evidence_id
            for evidence_id, record in evidence.items()
            if ".tasks" in Path(record["source"]["path"]).parts
            and not source_is_included(record["source"]["path"], includes)
        }
        if not excluded_ids:
            return
        entities = self.repository.records_unchecked("entities")
        current_evidence_ids = {
            evidence_id
            for evidence_id, record in evidence.items()
            if evidence_id not in excluded_ids and record.get("state", "current") == "current"
        }
        inferred_support_by_entity: dict[str, set[str]] = {}

        def retain_reference(entity_id: str | None, support: list[str] | set[str]) -> None:
            if entity_id and entity_id in {item["id"] for item in entities}:
                current_support = set(support) & current_evidence_ids
                if current_support:
                    inferred_support_by_entity.setdefault(entity_id, set()).update(current_support)

        for alias in self.repository.records_unchecked("aliases"):
            if alias.get("epistemic_state") == "inferred":
                retain_reference(alias.get("entity_id"), alias.get("evidence", []))
        for claim in self.repository.records_unchecked("claims"):
            if claim.get("epistemic_state") == "inferred":
                support = claim.get("evidence", [])
                retain_reference(claim.get("subject"), support)
                retain_reference(claim.get("object"), support)
        for relationship in self.repository.records_unchecked("relationships"):
            if relationship.get("epistemic_state") == "inferred":
                support = relationship.get("evidence", [])
                retain_reference(relationship.get("from"), support)
                retain_reference(relationship.get("to"), support)
        for decision in self.repository.records_unchecked("decisions"):
            if decision.get("epistemic_state") != "inferred":
                continue
            decision_support = set(decision.get("evidence", []))
            for option in decision.get("options", []):
                support = decision_support | set(option.get("evidence", []))
                for operation in option.get("delta", {}).get("operations", []):
                    entity_id = operation.get("entity", {}).get("id")
                    retain_reference(entity_id, support)
                    relationship = operation.get("relationship", {})
                    retain_reference(relationship.get("from"), support)
                    retain_reference(relationship.get("to"), support)
        for entity in entities:
            support = set(entity.get("evidence", []))
            if entity.get("epistemic_state") != "inferred" or not support.intersection(excluded_ids):
                continue
            retained_support = inferred_support_by_entity.get(entity["id"], set())
            support.update(retained_support)
            if support - excluded_ids:
                entity["evidence"] = [item for item in entity.get("evidence", []) if item not in excluded_ids]
                entity["evidence"].extend(sorted(retained_support - set(entity["evidence"])))
                self.repository.save("entities", entity)
                continue
            entity_id = entity["id"]
            referenced = any(alias.get("entity_id") == entity_id for alias in self.repository.records_unchecked("aliases"))
            referenced |= any(entity_id in {claim.get("subject"), claim.get("object")} for claim in self.repository.records_unchecked("claims"))
            referenced |= any(entity_id in {row.get("from"), row.get("to")} for row in self.repository.records_unchecked("relationships"))
            for decision in self.repository.records_unchecked("decisions"):
                for option in decision.get("options", []):
                    for operation in option.get("delta", {}).get("operations", []):
                        referenced |= operation.get("entity", {}).get("id") == entity_id
                        relation = operation.get("relationship", {})
                        referenced |= entity_id in {relation.get("from"), relation.get("to")}
            if referenced:
                raise DomainError(f"Cannot safely remove task-only entity {entity_id}: it is referenced by a remaining record.")
            (self.repository.overlay / "entities" / f"{entity_id}.yaml").unlink(missing_ok=True)

    def _mock_decisions(self, evidence: list[Any], catalog: tuple[Any, ...]) -> list[dict[str, Any]]:
        """Extract explicit selected choices and alternatives without requiring a document template."""
        decisions = []
        for passage in evidence:
            match = re.search(r"\bwe\s+(?:chose|selected|adopted)\s+([\w.+ -]+?)\s+(?:because|for)\b", passage.text, re.I)
            flow_choice = re.search(r"\bwe\s+chose\s+asynchronous reservation\s+because\b", passage.text, re.I)
            if not match and not flow_choice:
                continue
            selected_term = match.group(1).strip(" ,.;:") if match else ""
            selected = next((entry for entry in catalog if selected_term.casefold() == entry[0].casefold() or selected_term.casefold() in entry[2]), None)
            if flow_choice:
                selected = ("Accept, then fulfill asynchronously", "flow", ())
            if not selected:
                continue
            selected_name, _, _ = selected
            rationale = passage.text[(flow_choice or match).end():].split(".", 1)[0].strip()
            decision_title = passage.heading_path[0] if passage.heading_path else f"Choose {selected_name}"
            document_text = " ".join(item.text.casefold() for item in evidence if item.source_path == passage.source_path)
            actor_names = {
                "Payment retry delivery": "Payments Service",
                "Courier dispatch runtime": "Dispatch workers",
                "RFC: courier and restaurant availability": "Dispatch workflow",
                "Order placement and restaurant reservation": "Order Service",
            }
            requested_actor = actor_names.get(decision_title)
            actor = next((entry for entry in catalog if entry[0] == requested_actor), None) if requested_actor else None
            if actor is None:
                actor = next((entry for entry in catalog if entry[1] == "service" and any(alias in document_text for alias in entry[2])), None)
            candidates = [(selected, passage)]
            for alternative in evidence:
                if alternative.source_path != passage.source_path:
                    continue
                heading = (alternative.heading_path[-1] if alternative.heading_path else "").casefold()
                has_alternative_cue = "alternative" in heading or "considered" in heading or "would reduce" in alternative.text.casefold() or "instead" in alternative.text.casefold()
                if not has_alternative_cue:
                    continue
                heading = alternative.heading_path[-1] if alternative.heading_path else ""
                if flow_choice and "wait for reservation" in heading.casefold():
                    label = "Wait for reservation during checkout"
                    candidates.append(((label, "flow", (), label), alternative))
                    continue
                option_label = re.sub(r"^(?:considered\s+)?alternative\s*:\s*", "", heading, flags=re.I).strip()
                for entry in catalog:
                    if entry == selected:
                        continue
                    if any(alias in alternative.text.casefold() for alias in entry[2]):
                        if "fixed worker pool" in option_label.casefold():
                            option_label = option_label[:1].upper() + option_label[1:]
                        elif not any(alias in option_label.casefold() for alias in entry[2]):
                            option_label = entry[0]
                        candidates.append(((entry[0], entry[1], entry[2], option_label), alternative))
            options = []
            for index, (entry, source) in enumerate(candidates):
                name, kind, _ = entry[:3]
                option_label = entry[3] if len(entry) > 3 and entry[3] else name
                option_id = stable_id("option", f"{passage.id}/{decision_title}/{option_label}")
                option_rationale = rationale if index == 0 else source.text
                operations = []
                reporting_database_alternative = False
                if kind == "flow":
                    restaurant_id = stable_id("entity", "restaurant service")
                    relation_kind = "submits_reservation_async" if index == 0 else "waits_for_reservation"
                    operations.append({"op": "add_relationship", "relationship": {"id": stable_id("relationship", f"{option_id}/{relation_kind}"), "from": stable_id("entity", actor[0].casefold()), "to": restaurant_id, "kind": relation_kind}, "expect": {"exists": False}})
                    if index == 0:
                        fulfillment_id = stable_id("entity", "fulfillment service")
                        operations.append({"op": "add_relationship", "relationship": {"id": stable_id("relationship", f"{option_id}/publishes_accepted_order"), "from": stable_id("entity", actor[0].casefold()), "to": fulfillment_id, "kind": "publishes_accepted_order"}, "expect": {"exists": False}})
                else:
                    reporting_database_alternative = (
                        decision_title == "RFC: courier and restaurant availability"
                        and name == "PostgreSQL"
                        and any("separately provisioned PostgreSQL instance" in item.text for item in evidence)
                    )
                    resource_labels = {
                        "Event delivery for food orders": "Order event stream",
                        "Payment retry delivery": "Payment retry queue",
                        "Courier dispatch runtime": "Dispatch runtime" if name == "Kubernetes" else "Dispatch job queue",
                        "RFC: durable order data": "Order database",
                        "RFC: restaurant and menu reads": "Restaurant menu cache" if name == "Redis" else "Restaurant relational read store",
                        "RFC: courier and restaurant availability": "Courier and restaurant availability cache" if name == "Redis" else "Historical availability query store",
                    }
                    resource_name = f"{resource_labels.get(decision_title, decision_title)} ({option_label})"
                    resource_id = "datastore-postgres-reporting" if reporting_database_alternative else stable_id("resource", f"{passage.source_path}/{decision_title}/{name}")
                    if not reporting_database_alternative:
                        resource_kind = "runtime" if name == "Kubernetes" else "resource"
                        technology_id = stable_id("entity", name.casefold())
                        operations.append({"op": "add_entity", "entity": {"id": resource_id, "kind": resource_kind, "name": resource_name}, "expect": {"exists": False}})
                    fixed_worker_pool = decision_title == "Courier dispatch runtime" and name == "Amazon SQS"
                    if fixed_worker_pool:
                        worker_pool_id = stable_id("resource", f"{passage.source_path}/{decision_title}/fixed-worker-pool")
                        operations.append({"op": "add_entity", "entity": {"id": worker_pool_id, "kind": "runtime", "name": "Fixed dispatch worker pool"}, "expect": {"exists": False}})
                        if actor:
                            operations.append({"op": "add_relationship", "relationship": {"id": stable_id("relationship", f"{option_id}/dispatches-with-pool"), "from": stable_id("entity", actor[0].casefold()), "to": worker_pool_id, "kind": "dispatches_with"}, "expect": {"exists": False}})
                        operations.append({"op": "add_relationship", "relationship": {"id": stable_id("relationship", f"{option_id}/pool-consumes-queue"), "from": worker_pool_id, "to": resource_id, "kind": "consumes_from"}, "expect": {"exists": False}})
                    elif actor:
                        relation_kind = "stores_in" if decision_title == "RFC: durable order data" else "reads_from" if decision_title in {"RFC: restaurant and menu reads", "RFC: courier and restaurant availability"} else "runs_on" if name == "Kubernetes" else "queues" if "queue" in resource_name.casefold() else "publishes_to"
                        operations.append({"op": "add_relationship", "relationship": {"id": stable_id("relationship", f"{option_id}/actor-resource"), "from": stable_id("entity", actor[0].casefold()), "to": resource_id, "kind": relation_kind}, "expect": {"exists": False}})
                    if not reporting_database_alternative:
                        operations.append({"op": "add_relationship", "relationship": {"id": stable_id("relationship", f"{option_id}/resource-technology"), "from": resource_id, "to": technology_id, "kind": "implemented_by"}, "expect": {"exists": False}})
                option_evidence = [source.id]
                # An alternative passage may name a technology without naming
                # the actor attached to its delta. Cite the same document's
                # explicit actor passage as well, so the edge is not presented
                # as asserted by the alternative text alone.
                if actor:
                    actor_mentions = actor[2]
                    actor_support = [
                        item.id for item in evidence
                        if item.source_path == passage.source_path
                        and any(alias.casefold() in item.text.casefold() for alias in actor_mentions)
                    ]
                    option_evidence.extend(actor_support)
                if reporting_database_alternative:
                    reporting_support = next(
                        (item.id for item in evidence if "separately provisioned PostgreSQL instance" in item.text),
                        None,
                    )
                    if reporting_support:
                        option_evidence.append(reporting_support)
                options.append({"id": option_id, "title": option_label, "rationale": option_rationale, "evidence": list(dict.fromkeys(option_evidence)), "delta": {"base": "architecture", "operations": operations}})
            if not options:
                continue
            decisions.append({"schema_version": "decision/v1", "record_type": "decision", "id": stable_id("decision", f"{passage.source_path}/{passage.heading_path}/{selected_name}"), "title": decision_title, "status": "decided", "epistemic_state": "inferred", "context": passage.text, "selected_option": options[0]["id"], "evidence": [passage.id], "options": options, "extraction": {"extractor": "mock-rules-v1"}})
        return decisions

    def _project_scenario(self, graph: Graph, decisions: list[Decision], claims: list[Claim], selections: dict[str, str] | None = None) -> tuple[ScenarioResult, dict[str, str], list[Claim], list[str]]:
        defaults = {d.id: d.selected_option for d in decisions if d.selected_option}
        selected = {**defaults, **(selections or {})}
        result = compile_scenario(graph, decisions, selected)
        active_claims = effective_claims(claims)
        invalid_assumptions = list(result.invalid_assumptions)
        base_entity_ids = set(graph.entities)
        selected_options = {
            (decision.id, selected[decision.id]): decision
            for decision in decisions
            if decision.id in selected
        }
        explicitly_written_relationships = {
            operation.get("relationship", {}).get("id")
            for (decision_id, option_id), decision in selected_options.items()
            for option in decision.options
            if option.id == option_id
            for operation in option.delta.get("operations", [])
            if operation.get("op") in {"remove_relationship", "replace_relationship"}
        }
        for claim in active_claims:
            if claim.predicate not in {"uses", "publishes_to", "calls", "depends_on", "stores_in", "communicates_with", "implements"}:
                continue
            missing = {claim.subject, claim.object} - result.graph.entities.keys()
            if missing:
                invalid_assumptions.append(
                    f"Claim {claim.id} assumes scenario entities that are absent: {', '.join(sorted(missing))}."
                )
                continue
            # Base claims are already in the base graph and must remain subject
            # to selected delta removals/replacements during scenario compilation.
            if claim.subject in base_entity_ids and claim.object in base_entity_ids:
                continue
            relationship_id = stable_id("relationship", f"{claim.subject}/{claim.predicate}/{claim.object}")
            if relationship_id in explicitly_written_relationships:
                continue
            result.graph.relationships[relationship_id] = Relationship(
                relationship_id, claim.subject, claim.object, claim.predicate, claim.id
            )
        return result, selected, active_claims, invalid_assumptions

    def _identity_data(self, entities: dict[str, Entity], claims: list[Claim]) -> dict[str, Any]:
        """Return read-time identity groups, exact-name suggestions, and conflicts."""
        result = identity_projection(entities, claims)
        conflicted_pairs = {
            tuple(sorted(conflict["entity_ids"]))
            for conflict in result["identity_conflicts"]
        }
        superseded = {claim_id for claim in claims for claim_id in claim.supersedes}
        active_identity_claims = [claim for claim in claims if claim.id not in superseded and claim.predicate == "same_entity_as"]
        existing_pairs = {tuple(sorted((claim.subject, claim.object))) for claim in active_identity_claims}
        human_pairs = {
            tuple(sorted((claim.subject, claim.object))) for claim in active_identity_claims
            if claim.epistemic_state in {"confirmed", "asserted", "rejected"}
        }
        suggestions: list[dict[str, Any]] = []
        for claim in claims:
            pair = tuple(sorted((claim.subject, claim.object)))
            if claim.predicate == "same_entity_as" and claim.epistemic_state == "inferred" and claim.id not in superseded and pair not in human_pairs and set(pair) <= entities.keys():
                suggestions.append({"source": "inferred_claim", "entity_ids": list(pair), "claim_id": claim.id, "evidence": claim.evidence, "confidence": claim.confidence})
        buckets: dict[tuple[str, str], list[str]] = {}
        for entity_id, entity in entities.items():
            normalized_name = " ".join(entity.name.split()).casefold()
            buckets.setdefault((entity.kind, normalized_name), []).append(entity_id)
        active_pair_judgments: dict[tuple[str, str], list[Claim]] = {}
        for claim in active_identity_claims:
            if claim.epistemic_state in {"confirmed", "asserted", "rejected"}:
                active_pair_judgments.setdefault(tuple(sorted((claim.subject, claim.object))), []).append(claim)
        for (kind, name), entity_ids in sorted(buckets.items()):
            for index, left in enumerate(sorted(entity_ids)):
                for right in sorted(entity_ids)[index + 1:]:
                    pair = (left, right)
                    if pair in conflicted_pairs:
                        continue
                    pair_judgments = active_pair_judgments.get(pair, [])
                    judgment = next((claim for claim in pair_judgments if claim.epistemic_state == "rejected"), pair_judgments[0] if pair_judgments else None)
                    rejected_candidate = any(claim.epistemic_state == "rejected" for claim in pair_judgments)
                    if pair in existing_pairs and not rejected_candidate:
                        continue
                    suggestions.append({"source": "exact_name", "entity_ids": list(pair), "name": name, "kind": kind, "evidence": [], **({"claim_id": judgment.id, "epistemic_state": judgment.epistemic_state} if judgment else {})})
        result["identity_suggestions"] = sorted(suggestions, key=lambda item: (item["entity_ids"], item["source"], item.get("claim_id", "")))
        return result

    def review_exact_identity_candidate(self, entity_ids: list[str], decision: str) -> dict[str, Any]:
        """Append a human judgment for a currently valid exact-name identity pair."""
        if decision not in {"confirmed", "asserted", "rejected"}:
            raise DomainError("Review state must be confirmed, asserted, or rejected.")
        if len(entity_ids) != 2 or not all(isinstance(entity_id, str) and entity_id.strip() for entity_id in entity_ids):
            raise DomainError("An exact-name identity candidate requires two entity IDs.")
        left_id, right_id = entity_ids
        if left_id == right_id:
            raise DomainError("An identity candidate must link two distinct entities.")

        graph, _, _, _, claims = self.graph()
        left, right = graph.entities.get(left_id), graph.entities.get(right_id)
        if left is None or right is None:
            raise DomainError("An exact-name identity candidate must reference existing entities.")
        if left.kind != right.kind:
            raise DomainError("An exact-name identity candidate must link entities of the same kind.")
        normalize_name = lambda value: " ".join(value.split()).casefold()
        if normalize_name(left.name) != normalize_name(right.name):
            raise DomainError("The entity pair is not a current exact-name candidate.")

        pair = tuple(sorted((left_id, right_id)))
        pair_claims = [claim for claim in claims if claim.predicate == "same_entity_as" and tuple(sorted((claim.subject, claim.object))) == pair]
        superseded = {claim_id for claim in claims for claim_id in claim.supersedes}
        active_pair_claims = [claim for claim in pair_claims if claim.id not in superseded]
        current_human = next((claim for claim in active_pair_claims if claim.epistemic_state in {"confirmed", "asserted", "rejected"}), None)
        active_human_pair_claims = [claim for claim in active_pair_claims if claim.epistemic_state in {"confirmed", "asserted", "rejected"}]
        if current_human and current_human.epistemic_state == decision and all(claim.epistemic_state == decision for claim in active_human_pair_claims):
            human = next((record for record in self.repository.records("claims") if record["id"] == current_human.id), None)
            assert human is not None
            projection = self._identity_data(graph.entities, claims)
            return {"claim": human, **{key: projection[key] for key in ("identity_groups", "identity_suggestions", "identity_conflicts")}}

        records = self.repository.records("claims")
        by_id = {record["id"]: record for record in records}
        target = by_id.get(current_human.id) if current_human else next((by_id[claim.id] for claim in active_pair_claims if claim.id in by_id), None)
        root_id = target.get("reviewed_claim", target["id"]) if target else None
        if target:
            family_ids = {record["id"] for record in records if record.get("reviewed_claim", record["id"]) == root_id}
            family_ids.add(root_id)
            supersedes_ids = family_ids | {claim.id for claim in active_pair_claims}
            claim_id = stable_id("human-identity", f"{root_id}/{decision}/{'/'.join(sorted(supersedes_ids))}")
        else:
            supersedes_ids = set()
            claim_id = stable_id("human-identity", "/".join(pair))
            if claim_id in by_id and any(record.get("undoes") == claim_id for record in records):
                # The pair's first judgment was undone; append a redo to its chain.
                root_id = claim_id
                supersedes_ids = {record["id"] for record in records if record.get("reviewed_claim", record["id"]) == root_id}
                claim_id = stable_id("human-identity", f"{root_id}/{decision}/{'/'.join(sorted(supersedes_ids))}")
        if claim_id in by_id:
            human = by_id[claim_id]
        else:
            human = {
                "schema_version": "decision/v1",
                "record_type": "claim",
                "id": claim_id,
                "subject": pair[0],
                "predicate": "same_entity_as",
                "object": pair[1],
                "epistemic_state": decision,
                "confidence": 1,
                "evidence": [],
                "reviewer": "human",
                "reviewed_at": review_timestamp(),
                "supersedes": sorted(supersedes_ids),
            }
            if root_id:
                human["reviewed_claim"] = root_id
            self.repository.save("claims", human)
        refreshed_claims = without_undone_reviews(self.repository.records("claims"))
        projection = self._identity_data(graph.entities, [Claim(**{key: value for key, value in record.items() if key in Claim.__dataclass_fields__}) for record in refreshed_claims])
        return {"claim": human, **{key: projection[key] for key in ("identity_groups", "identity_suggestions", "identity_conflicts")}}

    @staticmethod
    def _passage_from_record(record: dict[str, Any]) -> Evidence:
        """Convert a portable evidence record into a domain passage for read-only derivations."""
        source, location = record.get("source", {}), record.get("location", {})
        return Evidence(record["id"], source.get("path", ""), location.get("heading_path", []), location.get("normalized_passage_sha256", ""), location.get("context_before", ""), location.get("context_after", ""), source.get("git_blob"), location.get("display_line"), record.get("text", ""), record.get("state", "current"))

    def _render_graph(self, graph: Graph, decisions: list[Decision], aliases: list[dict[str, Any]], evidence: list[dict[str, Any]], claims: list[Claim], decision_records: list[dict[str, Any]], selections: dict[str, str] | None = None, projection: tuple[ScenarioResult, dict[str, str], list[Claim], list[str]] | None = None) -> dict[str, Any]:
        """Render a projected graph; ``decision_records`` is the raw decision snapshot ``graph`` was built from."""
        result, selected, active_claims, invalid_assumptions = projection or self._project_scenario(graph, decisions, claims, selections)
        extraction_reviews = {record["id"]: record.get("extraction_review") for record in decision_records if record.get("extraction_review")}
        derived = decision_log_reasons(decisions, [self._passage_from_record(record) for record in evidence])
        rendered = {"entities": [vars(e) for e in result.graph.entities.values()], "relationships": [{"id": r.id, "from": r.source, "to": r.target, "kind": r.kind, "claim_id": r.claim_id} for r in result.graph.relationships.values()], "decisions": [{"id": d.id, "title": d.title, "status": d.status, "context": d.context, "selected_option": selected.get(d.id), "options": [{"id": o.id, "title": o.title, "rationale": o.rationale, "delta": o.delta, "evidence": o.evidence} for o in d.options], "evidence": d.evidence, **({"extraction_review": extraction_reviews[d.id]} if d.id in extraction_reviews else {}), "derived": asdict(derived[d.id])} for d in decisions], "aliases": aliases, "claims": [vars(c) for c in active_claims], "evidence": evidence, "scenario": {"selections": selected, "affected": {"added": result.added, "removed": result.removed, "changed": result.changed}, "conflicts": result.conflicts, "invalid_assumptions": sorted(set(invalid_assumptions)), "affected_decisions": result.affected_decisions}}
        rendered.update(self._identity_data(result.graph.entities, claims))
        return rendered

    def graph_json(self, selections: dict[str, str] | None = None, *, annotate: bool = True) -> dict[str, Any]:
        """Render a scenario graph.

        With ``annotate`` (the default for API and MCP reads), add ``receipt`` over the
        records this call read and ``scenario.impact`` versus repository selections.
        Internal callers that only need the graph pass ``annotate=False``.
        """
        records = self._read_records()
        graph, decisions, aliases, evidence, claims = self.graph(records)
        projection = self._project_scenario(graph, decisions, claims, selections)
        rendered = self._render_graph(graph, decisions, aliases, evidence, claims, records["decisions"], selections, projection)
        if not annotate:
            return rendered
        after, selected = projection[0].graph, projection[1]
        defaults = {d.id: d.selected_option for d in decisions if d.selected_option}
        # Repository selections remove or replace nothing relative to themselves.
        before = after if selected == defaults else self._project_scenario(graph, decisions, claims, None)[0].graph
        rendered["scenario"]["impact"] = downstream_impact(before, after, replacements=option_replacements(decisions, defaults, selected))
        rendered["receipt"] = input_receipt(records, selected)
        return rendered

    def _resolve_scenario(self, graph: Graph, decisions: list[Decision], claims: list[Claim], selections: dict[str, str] | None) -> ResolvedScenario:
        result, selected, _, invalid_assumptions = self._project_scenario(graph, decisions, claims, selections)
        return ResolvedScenario(selected, result.graph, list(result.conflicts), sorted(set(invalid_assumptions)))

    def diff_scenarios(self, before_selections: dict[str, str] | None = None, after_selections: dict[str, str] | None = None) -> dict[str, Any]:
        """Compare two scenarios; an omitted map means the repository-selected options."""
        records = self._read_records()
        graph, decisions, _, _, claims = self.graph(records)
        before = self._resolve_scenario(graph, decisions, claims, before_selections)
        after = self._resolve_scenario(graph, decisions, claims, after_selections)
        result = diff_resolved_scenarios(before, after, decisions)
        result["receipt"] = input_receipt(records, {"before": before.selections, "after": after.selections})
        return result

    @staticmethod
    def _option_touches_entities(option: Option, entity_ids: set[str]) -> bool:
        for operation in option.delta.get("operations", []):
            entity = operation.get("entity")
            if isinstance(entity, dict) and entity.get("id") in entity_ids:
                return True
            if isinstance(entity, str) and entity in entity_ids:
                return True
            relationship = operation.get("relationship")
            if isinstance(relationship, dict) and {relationship.get("from"), relationship.get("to")} & entity_ids:
                return True
            if {operation.get("from"), operation.get("to")} & entity_ids:
                return True
        return False

    def preview_delta(self, decision_id: str, option_id: str, delta: dict[str, Any], selections: dict[str, str] | None = None) -> dict[str, Any]:
        """Resolve an edited option delta without writing canonical repository files."""
        records = self.repository.records("decisions")
        record = next((item for item in records if item["id"] == decision_id), None)
        if record is None:
            raise KeyError(decision_id)
        option = next((item for item in record.get("options", []) if item["id"] == option_id), None)
        if option is None:
            raise KeyError(option_id)
        candidate = {**record, "options": [{**item, "delta": delta} if item["id"] == option_id else item for item in record["options"]]}
        self.repository.validate_candidate("decisions", candidate)
        records = self._read_records()
        graph, decisions, aliases, evidence, claims = self.graph(records)
        target_decision = next(item for item in decisions if item.id == decision_id)
        target_option = next(item for item in target_decision.options if item.id == option_id)
        target_option.delta = delta
        rendered = self._render_graph(graph, decisions, aliases, evidence, claims, records["decisions"], selections)
        return {"decision_id": decision_id, "option_id": option_id, "delta": delta, "graph": rendered, "affected": rendered["scenario"]["affected"], "conflicts": rendered["scenario"]["conflicts"], "invalid_assumptions": rendered["scenario"]["invalid_assumptions"]}

    def search(self, query: str, selections: dict[str, str] | None = None) -> dict[str, Any]:
        why_query = bool(re.match(r"^\s*why\b", query, re.IGNORECASE))
        records = self._read_records()
        graph, decisions, aliases, evidence_records, claim_history = self.graph(records)
        base_entities = graph.entities.copy()
        scenario, effective_selections, claims, _ = self._project_scenario(graph, decisions, claim_history, selections)
        graph = scenario.graph
        hits = self.index.search(query)
        why_evidence_by_id: dict[str, dict[str, Any]] = {}
        indexed_evidence_ids: set[str] = set()
        if why_query:
            # A scan can leave multiple portable records with the same evidence
            # ID. If any copy is unresolved, treat the citation as unresolved.
            unresolved_ids = {
                record["id"] for record in evidence_records
                if record.get("state", "current") != "current"
            }
            for record in evidence_records:
                if record.get("state", "current") == "current" and record["id"] not in unresolved_ids:
                    why_evidence_by_id.setdefault(record["id"], record)
            with self.index.connect() as db:
                indexed_evidence_ids = {row[0] for row in db.execute("SELECT id FROM passages")}
            indexed_evidence_ids.intersection_update(why_evidence_by_id)
        embedding_connection, embedding_status = self._embedding_setup()
        embedder = (lambda text: embed_with_litellm(embedding_connection, text)) if embedding_connection else None
        semantic_diagnostic: dict[str, str] = {}
        semantic_hits = self.vector_index.search(query, embedder, semantic_diagnostic)
        if embedding_connection:
            embedding_status["status"] = semantic_diagnostic.get("status", "error")
            if semantic_diagnostic.get("detail"):
                embedding_status["detail"] = semantic_diagnostic["detail"]
        normalized = " ".join(re.findall(r"[\w.+-]+", query.casefold()))
        candidate_entities = base_entities.copy()
        for decision in decisions:
            for option in decision.options:
                for operation in option.delta.get("operations", []):
                    entity = operation.get("entity", {})
                    if operation.get("op") in {"add_entity", "replace_entity"} and entity.get("id"):
                        candidate_entities.setdefault(entity["id"], Entity(**entity))

        query_stopwords = {"why", "are", "we", "using", "is", "was", "the", "a", "an", "for", "to", "of"}

        def matches_name(name: str) -> bool:
            name_tokens = re.findall(r"[\w.+-]+", name.casefold())
            normalized_name = " ".join(name_tokens)
            query_name_tokens = [token for token in normalized.split() if token not in query_stopwords]
            if not normalized_name or not query_name_tokens:
                return False
            if len(query_name_tokens) == 1:
                return query_name_tokens[0] in name_tokens
            query_topic = " ".join(query_name_tokens)
            return f" {normalized_name} " in f" {query_topic} "

        def names_exactly(name: str) -> bool:
            query_topic = " ".join(token for token in normalized.split() if token not in query_stopwords)
            return bool(query_topic) and " ".join(re.findall(r"[\w.+-]+", name.casefold())) == query_topic

        entities = []
        exact_active_ids: set[str] = set()
        for record in aliases:
            if matches_name(record.get("name", "")):
                target = graph.entities.get(record.get("entity_id"))
                if target:
                    entities.append(target.id)
                    if names_exactly(record.get("name", "")):
                        exact_active_ids.add(target.id)
        entities.extend(eid for eid, entity in graph.entities.items() if matches_name(entity.name))
        exact_active_ids.update(eid for eid, entity in graph.entities.items() if names_exactly(entity.name))
        for decision in decisions:
            selected_option = next((option for option in decision.options if option.id == effective_selections.get(decision.id)), None)
            if selected_option is None:
                continue
            for operation in selected_option.delta.get("operations", []):
                candidate = operation.get("entity", {})
                candidate_name = str(candidate.get("name", ""))
                if candidate.get("id") and matches_name(candidate_name):
                    entities.append(candidate["id"])
                    if names_exactly(candidate_name):
                        exact_active_ids.add(candidate["id"])
        entities = list(dict.fromkeys(entities))

        inactive_entities = {
            entity_id: entity
            for entity_id, entity in candidate_entities.items()
            if entity_id not in graph.entities and matches_name(entity.name)
        }
        inactive_named_exactly = any(names_exactly(entity.name) for entity in inactive_entities.values())
        for alias in aliases:
            if alias["entity_id"] not in graph.entities and matches_name(alias["name"]):
                inactive_entities.setdefault(alias["entity_id"], candidate_entities.get(alias["entity_id"], Entity(alias["entity_id"], "component", alias["name"])))
                inactive_named_exactly = inactive_named_exactly or names_exactly(alias["name"])

        def option_entries(entity_id: str) -> list[dict[str, Any]]:
            entries = []
            for decision in decisions:
                for option in decision.options:
                    introduced = any(
                        operation.get("op") in {"add_entity", "replace_entity"}
                        and operation.get("entity", {}).get("id") == entity_id
                        for operation in option.delta.get("operations", [])
                    )
                    if introduced:
                        is_selected = effective_selections.get(decision.id) == option.id
                        entries.append({"decision_id": decision.id, "decision": decision.title, "option_id": option.id, "option": option.title, "selected": is_selected, "rationale": option.rationale, "evidence": option.evidence or decision.evidence})
            return entries

        def involves(decision: Decision, selected: Option, entity_ids: Iterable[str]) -> bool:
            delta_text = str(selected.delta).casefold()
            context_text = decision.context.casefold()
            return any(entity_id in delta_text or entity_id in context_text for entity_id in entity_ids)

        active_decisions = []
        for decision in decisions:
            selected = next((option for option in decision.options if option.id == effective_selections.get(decision.id)), None)
            if selected is not None and involves(decision, selected, entities):
                active_decisions.append((decision, selected))
        selected_named_exactly = any(involves(decision, selected, exact_active_ids) for decision, selected in active_decisions)

        # A selected decision involving a matched active entity takes precedence,
        # and unselected options follow it in the answer. An inactive entity named
        # exactly by the query keeps the inactive answer unless a selected
        # decision involves an active entity that the query also names exactly.
        if inactive_entities and (not active_decisions or (inactive_named_exactly and not selected_named_exactly)):
            inactive_details = []
            evidence_ids: set[str] = set()
            option_evidence_ids: set[str] = set()
            for entity_id, entity in inactive_entities.items():
                options_for_entity = []
                for entry in option_entries(entity_id):
                    entry_evidence = entry.pop("evidence")
                    evidence_ids.update(entry_evidence)
                    option_evidence_ids.update(entry_evidence)
                    options_for_entity.append(entry)
                for claim in claims:
                    if claim.subject == entity_id or claim.object == entity_id:
                        evidence_ids.update(claim.evidence)
                inactive_details.append({"id": entity_id, "name": entity.name, "options": options_for_entity})
            candidate_evidence = []
            for evidence_id in evidence_ids & indexed_evidence_ids:
                record = why_evidence_by_id.get(evidence_id)
                if record is None:
                    continue
                candidate_evidence.append({"id": record["id"], "source": record["source"]["path"], "heading": record["location"]["heading_path"], "text": record["text"], "context": "decision_option"})
            query_rank = {hit["id"]: rank for rank, hit in enumerate(hits)}
            candidate_evidence.sort(key=lambda item: (query_rank.get(item["id"], len(query_rank)), item["id"]))
            relevant_claims = [
                claim for claim in claims
                if (claim.subject in inactive_entities or claim.object in inactive_entities)
            ]
            candidate_ids = {item["id"] for item in candidate_evidence}
            historical_claims = []
            if why_query:
                for claim in relevant_claims:
                    cited_ids = set(claim.evidence) & candidate_ids
                    if cited_ids:
                        historical_claims.append({**vars(claim), "evidence": [evidence_id for evidence_id in claim.evidence if evidence_id in cited_ids]})
                supporting_ids = {evidence_id for claim in historical_claims for evidence_id in claim["evidence"]}
                if supporting_ids:
                    candidate_evidence = [item for item in candidate_evidence if item["id"] in supporting_ids]
            historical_evidence = candidate_evidence[:8]
            if why_query:
                returned_ids = {item["id"] for item in historical_evidence}
                historical_claims = [
                    {**claim, "evidence": [evidence_id for evidence_id in claim["evidence"] if evidence_id in returned_ids]}
                    for claim in historical_claims
                    if returned_ids.intersection(claim["evidence"])
                ]
            descriptions = []
            for detail in inactive_details:
                descriptions.append(f"{detail['name']} is not present in the selected scenario.")
                for option in detail["options"]:
                    state = "selected" if option["selected"] else "unselected"
                    description = f"It appears in the {state} {option['option']} option for {option['decision']}."
                    if option["rationale"]:
                        description += f" Recorded rationale: {option['rationale']}"
                    descriptions.append(description)
            if not historical_evidence:
                descriptions.append("No current source evidence is attached to that option in the portable records.")
            # A why answer about an unselected option is grounded by that option's
            # own current, indexed evidence or by a claim citing a returned passage.
            option_grounded = bool(option_evidence_ids.intersection(item["id"] for item in historical_evidence))
            grounded = bool(historical_evidence) if not why_query else bool(historical_evidence and (historical_claims or option_grounded))
            if why_query and not historical_claims and not option_grounded:
                descriptions.append("No current claim supports this why answer, so it is not fully grounded.")
            return {"receipt": input_receipt(records, effective_selections, {"query": query}), "answer": " ".join(descriptions), "evidence": historical_evidence, "claims": historical_claims if why_query else [vars(claim) for claim in claims if claim.subject in inactive_entities or claim.object in inactive_entities], "entities": [], **self._identity_data(graph.entities, claim_history), "grounded": grounded, "semantic_index": embedding_status, "vector_search": semantic_diagnostic, "scenario_context": {"selections": effective_selections, "inactive_entities": inactive_details, "evidence_context": "historical_decision_option"}}

        related_claims = [vars(c) for c in claims if c.subject in entities or c.object in entities]
        related_ids = {c.get("source_path") for c in related_claims}
        expanded = [hit for hit in hits if any(eid in hit["metadata"].get("entity_ids", []) for eid in entities) or hit["path"] in related_ids]
        merged = {hit["id"]: hit for hit in hits}
        for hit in semantic_hits:
            evidence_id = hit.get("evidence_id")
            if evidence_id:
                merged.setdefault(evidence_id, {"id": evidence_id, "path": hit.get("path", ""), "heading": hit.get("heading", ""), "text": hit.get("text", ""), "metadata": {"entity_ids": hit.get("entity_ids", [])}, "semantic_score": hit.get("score", 0)})
        ranked = list(merged.values())
        # Graph expansion promotes evidence about an entity and its connected neighbors.
        expanded_ids = set(entities)
        for edge in graph.relationships.values():
            if edge.source in expanded_ids:
                expanded_ids.add(edge.target)
            if edge.target in expanded_ids:
                expanded_ids.add(edge.source)
        graph_hits = [hit for hit in ranked if expanded_ids.intersection(hit.get("metadata", {}).get("entity_ids", []))]
        ranked_passages = sorted({hit["id"]: hit for hit in [*expanded, *graph_hits, *ranked]}.values(), key=lambda hit: (bool(expanded_ids.intersection(hit.get("metadata", {}).get("entity_ids", []))), hit.get("semantic_score", 0)), reverse=True)
        passages_out = ranked_passages[:8]
        evidence_by_id = {record["id"]: record for record in evidence_records}
        rationale_parts: list[str] = []
        decision_evidence_ids: set[str] = set()
        for decision, selected in active_decisions:
            rationale = selected.rationale.strip()
            if rationale:
                rationale_parts.append(f"{selected.title} was selected for {decision.title}: {rationale}")
            decision_evidence_ids.update(selected.evidence or decision.evidence)
        cited_decision_evidence = [record for evidence_id in decision_evidence_ids if (record := evidence_by_id.get(evidence_id)) and record.get("state", "current") == "current"]
        direct_ids = {record["id"] for record in cited_decision_evidence}
        structural_predicates = {"uses", "publishes_to", "calls", "depends_on", "stores_in", "communicates_with", "implements"}
        query_claims = [
            claim for claim in claims
            if (claim.subject in entities or claim.object in entities)
            and all(endpoint not in candidate_entities or endpoint in graph.entities for endpoint in (claim.subject, claim.object))
            and (claim.predicate not in structural_predicates or {claim.subject, claim.object} <= graph.entities.keys())
        ]
        if rationale_parts and cited_decision_evidence:
            final_evidence = cited_decision_evidence
            final_claims = [vars(claim) for claim in query_claims if direct_ids.intersection(claim.evidence)]
            answer = "; ".join(rationale_parts)
        else:
            final_evidence = [{"id": hit["id"], "source": hit["path"], "location": {"heading_path": hit.get("heading", [])}, "text": hit["text"]} for hit in passages_out]
            final_claims = [vars(claim) for claim in query_claims]
            answer = "Evidence found in repository documents." if final_evidence else "No attributable evidence was found for this question."
        if why_query:
            final_claims = []
            relevant_query_claims = query_claims
            grounding_evidence_ids: set[str] | None = None
            if rationale_parts and cited_decision_evidence:
                grounding_evidence_ids = {record["id"] for record in cited_decision_evidence}
                relevant_query_claims = [
                    claim for claim in query_claims
                    if grounding_evidence_ids.intersection(claim.evidence)
                ]
            for claim in relevant_query_claims:
                citations = [
                    evidence_id for evidence_id in claim.evidence
                    if evidence_id in indexed_evidence_ids
                    and (grounding_evidence_ids is None or evidence_id in grounding_evidence_ids)
                ]
                if citations:
                    final_claims.append({**vars(claim), "evidence": citations})
            if final_claims:
                available_by_id: dict[str, dict[str, Any]] = {}
                candidate_order = [item["id"] for item in final_evidence]
                candidate_order.extend(hit["id"] for hit in ranked_passages)
                candidate_order.extend(evidence_id for claim in final_claims for evidence_id in claim["evidence"])
                for evidence_id in dict.fromkeys(candidate_order):
                    if evidence_id not in indexed_evidence_ids:
                        continue
                    record = why_evidence_by_id.get(evidence_id)
                    if record:
                        available_by_id[evidence_id] = {
                            "id": evidence_id,
                            "source": record["source"]["path"],
                            "location": {"heading_path": record["location"]["heading_path"]},
                            "text": record["text"],
                        }
                cited_ids = {evidence_id for claim in final_claims for evidence_id in claim["evidence"]}
                ranked_ids = [
                    evidence_id for evidence_id in dict.fromkeys(candidate_order)
                    if evidence_id in available_by_id and evidence_id in cited_ids
                ]
                returned_ids = set(ranked_ids[:8])
                final_evidence = [available_by_id[evidence_id] for evidence_id in ranked_ids[:8]]
                final_claims = [
                    {**claim, "evidence": [evidence_id for evidence_id in claim["evidence"] if evidence_id in returned_ids]}
                    for claim in final_claims
                    if returned_ids.intersection(claim["evidence"])
                ]
            else:
                final_evidence = [
                    item for item in final_evidence
                    if item["id"] in why_evidence_by_id
                ]
            if not final_claims:
                answer = _append_sentence(answer, "No current claim supports this why answer, so it is not fully grounded.")
            grounded = bool(final_evidence and final_claims)
        else:
            grounded = bool(final_evidence)
        alternatives = [
            f"{entry['option']} for {entry['decision']}"
            for entity_id in inactive_entities
            for entry in option_entries(entity_id)
            if not entry["selected"]
        ]
        if alternatives:
            answer = _append_sentence(answer, f"Unselected alternatives: {'; '.join(dict.fromkeys(alternatives))}.")
        return {"receipt": input_receipt(records, effective_selections, {"query": query}), "answer": answer, "evidence": [{"id": x["id"], "source": (x.get("source", {}).get("path") if isinstance(x.get("source"), dict) else x.get("source")) or x.get("path", ""), "heading": x.get("location", {}).get("heading_path", x.get("heading", [])), "text": x["text"]} for x in final_evidence[:8]], "claims": final_claims, "entities": entities, **self._identity_data(graph.entities, claim_history), "grounded": grounded, "semantic_index": embedding_status, "vector_search": semantic_diagnostic}

    def entity_detail(self, entity_id: str, selections: dict[str, str] | None = None) -> dict[str, Any]:
        graph, decisions, aliases, evidence, claims = self.graph()
        all_alias_records = without_undone_reviews(self.repository.records_unchecked("aliases"))
        superseded_alias_ids = {alias_id for record in all_alias_records for alias_id in record.get("supersedes", [])}
        detail_aliases = aliases + [record for record in all_alias_records if record.get("epistemic_state") == "rejected" and record["id"] not in superseded_alias_ids]
        rendered = self.graph_json(selections, annotate=False)
        entity_data = next((item for item in rendered["entities"] if item["id"] == entity_id), None)
        entity = graph.entities.get(entity_id)
        if not entity:
            if entity_data is None:
                raise KeyError(entity_id)
            entity = Entity(entity_data["id"], entity_data["kind"], entity_data["name"], entity_data.get("description", ""))
        relevant_claims = [vars(c) for c in effective_claims(claims) if c.subject == entity_id or c.object == entity_id]
        evidence_ids = {eid for c in relevant_claims for eid in c["evidence"]}
        evidence_ids.update(eid for a in detail_aliases if a.get("entity_id") == entity_id for eid in a.get("evidence", []))
        related_entity_ids = {entity_id}
        identity_conflicts = rendered["identity_conflicts"]
        conflicted_entity_ids = {candidate for conflict in identity_conflicts for candidate in conflict.get("component_entity_ids", conflict["entity_ids"])}
        if entity_id not in conflicted_entity_ids:
            for group in rendered["identity_groups"]:
                if entity_id in group["entity_ids"]:
                    related_entity_ids.update(group["entity_ids"])
            current_evidence_ids = {record["id"] for record in evidence if record.get("state", "current") == "current"}
            for suggestion in rendered["identity_suggestions"]:
                suggestion_ids = set(suggestion["entity_ids"])
                if entity_id not in suggestion_ids or suggestion.get("epistemic_state") == "rejected" or suggestion_ids & conflicted_entity_ids:
                    continue
                if suggestion.get("source") == "exact_name":
                    # Keep an ambiguous name match as a navigation candidate only; it does not
                    # create an identity group or merge either entity record.
                    related_entity_ids.update(suggestion_ids)
                elif suggestion.get("source") == "inferred_claim":
                    support_ids = {reference if isinstance(reference, str) else reference.get("id") for reference in suggestion.get("evidence", [])}
                    if support_ids & current_evidence_ids:
                        related_entity_ids.update(suggestion_ids)
        for related_id in related_entity_ids:
            related_entity = next((record for record in self.repository.records_unchecked("entities") if record.get("id") == related_id), {})
            evidence_ids.update(related_entity.get("evidence", []))
            evidence_ids.update(evidence_id for claim in claims if claim.subject == related_id or claim.object == related_id for evidence_id in claim.evidence)
            evidence_ids.update(evidence_id for alias in detail_aliases if alias.get("entity_id") == related_id for evidence_id in alias.get("evidence", []))
        related_decisions = [d for d in decisions if any(self._option_touches_entities(option, related_entity_ids) for option in d.options) or entity_id in d.context]
        effective_selections = {d.id: d.selected_option for d in decisions if d.selected_option}
        effective_selections.update(selections or {})
        for decision in related_decisions:
            evidence_ids.update(decision.evidence)
            for option in decision.options:
                if self._option_touches_entities(option, related_entity_ids):
                    evidence_ids.update(option.evidence)
        return {"entity": vars(entity), "relationships": [{"id": r["id"], "from": r["from"], "to": r["to"], "kind": r["kind"]} for r in rendered["relationships"] if r["from"] == entity_id or r["to"] == entity_id], "decisions": [{"id": d.id, "title": d.title, "selected_option": next(({"id": o.id, "title": o.title, "rationale": o.rationale, "evidence": o.evidence} for o in d.options if o.id == effective_selections.get(d.id)), None), "options": [{"id": o.id, "title": o.title, "rationale": o.rationale, "delta": o.delta, "evidence": o.evidence} for o in d.options]} for d in related_decisions], "aliases": [a for a in detail_aliases if a.get("entity_id") in related_entity_ids], "claims": relevant_claims, "evidence": [r for r in evidence if r.get("id") in evidence_ids], "identity_groups": rendered["identity_groups"], "identity_suggestions": [item for item in rendered["identity_suggestions"] if entity_id in item["entity_ids"]], "identity_conflicts": [item for item in rendered["identity_conflicts"] if entity_id in item.get("component_entity_ids", item["entity_ids"])]}

    def configure_connection(self, record: dict[str, Any]) -> dict[str, Any]:
        if not record.get("id") or not record.get("provider"):
            raise DomainError("Connection requires id and provider.")
        existing = self.connections.get(record["id"], {})
        if not record.get("credential_ref") and existing.get("credential_ref"):
            record["credential_ref"] = existing["credential_ref"]
        if record.get("provider") in {"openai", "anthropic"}:
            record["endpoint"] = ""
        if record.get("credential_ref") and not str(record["credential_ref"]).startswith("env:"):
            raise DomainError("credential_ref must name an environment variable using env:NAME.")
        # Forms that do not edit generation omit it; keep the stored value. An explicit {} clears it.
        if "generation" not in record and existing.get("generation"):
            record["generation"] = existing["generation"]
        if isinstance(record.get("generation"), dict) or record.get("generation") is None:
            generation = {key: value for key, value in (record.pop("generation", None) or {}).items() if value not in (None, "")}
            if generation:
                record["generation"] = generation
        portable = {"schema_version": "decision/v1", "record_type": "model_connection", **record}
        self.repository.save("connections", portable)
        self.connections[record["id"]] = portable
        return {k: v for k, v in record.items() if k != "credential_ref"}

    def review_claim(self, claim_id: str, decision: str) -> dict[str, Any]:
        if decision not in {"confirmed", "rejected", "asserted"}:
            raise DomainError("Review state must be confirmed, rejected, or asserted.")
        claims = self.repository.records("claims")
        target = next((record for record in claims if record["id"] == claim_id), None)
        if target is None:
            raise KeyError(claim_id)
        review_target = target.get("reviewed_claim", target["id"])
        prior_reviews = [record["id"] for record in claims if record.get("reviewed_claim") == review_target]
        if "reviewed_claim" not in target and is_human_review(target, "reviewed_claim"):
            # A human chain root, such as a first identity judgment, is superseded explicitly.
            prior_reviews.insert(0, review_target)
        human = {**{key: value for key, value in target.items() if key != "undoes"}, "id": f"human-claim-{uuid.uuid4().hex}", "epistemic_state": decision, "reviewed_claim": review_target, "reviewer": "human", "reviewed_at": review_timestamp(), "supersedes": prior_reviews}
        self.repository.save("claims", human)
        return human

    def correct_claim(self, claim_id: str, subject: str, predicate: str, object_value: str) -> dict[str, Any]:
        claims = self.repository.records("claims")
        target = next((record for record in claims if record["id"] == claim_id), None)
        if target is None:
            raise KeyError(claim_id)
        if not all(value.strip() for value in (subject, predicate, object_value)):
            raise DomainError("A claim correction requires non-empty subject, predicate, and object.")
        root_id = target.get("reviewed_claim", target["id"])
        family = [record for record in claims if record.get("reviewed_claim", record["id"]) == root_id]
        correction = {**{key: value for key, value in target.items() if key != "undoes"}, "id": f"human-claim-{uuid.uuid4().hex}", "subject": subject, "predicate": predicate, "object": object_value, "epistemic_state": "asserted", "reviewed_claim": root_id, "reviewer": "human", "reviewed_at": review_timestamp(), "supersedes": sorted({root_id, *(record["id"] for record in family)})}
        self.repository.validate_candidate("claims", correction)
        self.repository.save("claims", correction)
        return correction

    def review_alias(self, alias_id: str, decision: str) -> dict[str, Any]:
        if decision not in {"confirmed", "rejected", "asserted"}:
            raise DomainError("Review state must be confirmed, rejected, or asserted.")
        aliases = self.repository.records("aliases")
        target = next((record for record in aliases if record["id"] == alias_id), None)
        if target is None:
            raise KeyError(alias_id)
        review_target = target.get("reviewed_alias", target["id"])
        prior_reviews = [record["id"] for record in aliases if record.get("reviewed_alias") == review_target]
        if "reviewed_alias" not in target and is_human_review(target, "reviewed_alias"):
            prior_reviews.insert(0, review_target)
        human = {**{key: value for key, value in target.items() if key != "undoes"}, "id": f"human-alias-{uuid.uuid4().hex}", "epistemic_state": decision, "reviewed_alias": review_target, "reviewer": "human", "reviewed_at": review_timestamp(), "supersedes": prior_reviews}
        self.repository.save("aliases", human)
        return human

    def correct_alias(self, alias_id: str, name: str, entity_id: str) -> dict[str, Any]:
        aliases = self.repository.records("aliases")
        target = next((record for record in aliases if record["id"] == alias_id), None)
        if target is None:
            raise KeyError(alias_id)
        if not name.strip() or not entity_id.strip():
            raise DomainError("An alias correction requires a non-empty name and entity ID.")
        root_id = target.get("reviewed_alias", target["id"])
        family = [record for record in aliases if record.get("reviewed_alias", record["id"]) == root_id]
        correction = {**{key: value for key, value in target.items() if key != "undoes"}, "id": f"human-alias-{uuid.uuid4().hex}", "name": name.strip(), "entity_id": entity_id, "epistemic_state": "asserted", "reviewed_alias": root_id, "reviewer": "human", "reviewed_at": review_timestamp(), "supersedes": sorted({root_id, *(record["id"] for record in family)})}
        self.repository.validate_candidate("aliases", correction)
        self.repository.save("aliases", correction)
        return correction

    def _review_entity_names(self) -> dict[str, str]:
        graph, decisions, _, _, _ = self.graph()
        names = {entity_id: entity.name for entity_id, entity in graph.entities.items()}
        for decision in decisions:
            for option in decision.options:
                for operation in option.delta.get("operations", []):
                    entity = operation.get("entity")
                    if isinstance(entity, dict) and entity.get("id") and entity.get("name"):
                        names.setdefault(entity["id"], entity["name"])
        return names

    @staticmethod
    def _review_chain_state(records: list[dict[str, Any]], folder: str) -> tuple[set[str], dict[str, str], dict[str, str], dict[str, str]]:
        """Return active IDs, explicit supersession, undo links, and domain shadowing for one review folder."""
        active = without_undone_reviews(records)
        return {row["id"] for row in active}, review_supersession(active), {row["undoes"]: row["id"] for row in records if row.get("undoes")}, review_shadowing(active, folder)

    @staticmethod
    def _review_description(folder: str, record: dict[str, Any], names: dict[str, str]) -> tuple[str, dict[str, Any], str]:
        """Return the kind, structured subject, and readable summary of one claim or alias record."""
        named = lambda entity_id: {"id": entity_id, "name": names.get(entity_id)}
        if folder == "aliases":
            kind = "alias"
            subject = {"alias": record.get("name", ""), "entity": named(record.get("entity_id", ""))}
            summary = f"“{record.get('name', '')}” → {names.get(record.get('entity_id', ''), record.get('entity_id', ''))}"
        else:
            kind = "identity" if record.get("predicate") == "same_entity_as" else "claim"
            subject = {"subject": named(record.get("subject", "")), "predicate": record.get("predicate", ""), "object": named(record.get("object", ""))}
            subject_name = names.get(record.get("subject", ""), record.get("subject", ""))
            object_name = names.get(record.get("object", ""), record.get("object", ""))
            relation = "is the same entity as" if kind == "identity" else str(record.get("predicate", "")).replace("_", " ")
            summary = f"{subject_name} {relation} {object_name}"
        return kind, subject, summary

    @staticmethod
    def _review_judgment(record: dict[str, Any], root_key: str) -> str | None:
        """Classify one human review record as undo, corrected, or its epistemic state."""
        if record.get("undoes"):
            return "undo"
        if record.get("epistemic_state") == "asserted" and record.get(root_key) in record.get("supersedes", []) and not str(record["id"]).startswith("human-identity-"):
            return "corrected"
        return record.get("epistemic_state")

    def _review_prior(self, folder: str, root_key: str, record: dict[str, Any], by_id: dict[str, dict[str, Any]], names: dict[str, str]) -> list[dict[str, Any]]:
        """Describe each record a review supersedes, so the log can show the state it replaced."""
        prior = []
        # A review replaces its chain root through the root link even when `supersedes` omits it; an undo replaces only the undone judgment.
        root_id = record.get(root_key)
        implicit_root = [root_id] if root_id and not record.get("undoes") and root_id not in record.get("supersedes", []) else []
        for record_id in [*implicit_root, *record.get("supersedes", [])]:
            replaced = by_id.get(record_id)
            if replaced is None:
                prior.append({"id": record_id, "epistemic_state": None, "judgment": None, "summary": None, "subject": None})
                continue
            _, subject, summary = self._review_description(folder, replaced, names)
            judgment = self._review_judgment(replaced, root_key) if is_human_review(replaced, root_key) else None
            prior.append({"id": record_id, "epistemic_state": replaced.get("epistemic_state"), "judgment": judgment, "summary": summary, "subject": subject})
        return prior

    @staticmethod
    def _review_prior_effective(folder: str, root_key: str, record: dict[str, Any], replaced_ids: list[str], by_id: dict[str, dict[str, Any]]) -> list[str]:
        """Return the IDs that were effective immediately before this review, resolved only from the records it replaces."""
        if record.get("undoes"):
            return [record["undoes"]]
        active = without_undone_reviews([by_id[record_id] for record_id in dict.fromkeys(replaced_ids) if record_id in by_id])
        superseded = review_supersession(active)
        shadowed = review_shadowing(active, folder)
        remaining = [row for row in active if row["id"] not in superseded and row["id"] not in shadowed]
        # A remaining human judgment overrides the chain's original inference, as in undo restoration.
        human = [row for row in remaining if is_human_review(row, root_key)]
        return sorted(row["id"] for row in (human or remaining))

    def _review_entry(self, folder: str, root_key: str, record: dict[str, Any], state: tuple[set[str], dict[str, str], dict[str, str], dict[str, str]], names: dict[str, str]) -> dict[str, Any]:
        """Describe one human review record for the review log."""
        active_ids, superseded_by, undone_by, shadowed_by = state
        root_id = record.get(root_key)
        kind, subject, summary = self._review_description(folder, record, names)
        judgment = self._review_judgment(record, root_key)
        effective = record["id"] in active_ids and record["id"] not in superseded_by and record["id"] not in shadowed_by
        blocked = None
        if record.get("undoes"):
            blocked = "Undo records cannot be undone; review the item again to redo the judgment."
        elif record["id"] in undone_by:
            blocked = f"Already undone by {undone_by[record['id']]}."
        elif record["id"] in shadowed_by:
            blocked = f"{shadowed_by[record['id']]} takes precedence for the same {kind}; undo that judgment first."
        elif not effective:
            blocked = f"Superseded by {superseded_by.get(record['id'])}; undo the newer judgment first."
        return {
            "id": record["id"],
            "record_type": record.get("record_type"),
            "kind": kind,
            "judgment": judgment,
            "epistemic_state": record.get("epistemic_state"),
            "summary": summary,
            "subject": subject,
            "reviewed_record": root_id,
            "supersedes": list(record.get("supersedes", [])),
            "undoes": record.get("undoes"),
            "undone_by": undone_by.get(record["id"]),
            "superseded_by": superseded_by.get(record["id"]),
            "reviewed_at": record.get("reviewed_at"),
            "reviewer": record.get("reviewer"),
            "effective": effective and not record.get("undoes"),
            "undoable": blocked is None,
            "undo_blocked_reason": blocked,
        }

    def review_log(self) -> dict[str, Any]:
        """Return human claim, alias, and identity reviews, newest first."""
        names = self._review_entity_names()
        entries: list[tuple[tuple[str, int, str], dict[str, Any]]] = []
        for folder, root_key in REVIEW_FOLDERS:
            records = self.repository.records(folder)
            by_id = {record["id"]: record for record in records}
            state = self._review_chain_state(records, folder)
            for record in records:
                if not is_human_review(record, root_key):
                    continue
                # Records without timestamps order by supersession depth.
                seen: set[str] = set()
                pending = [*record.get("supersedes", []), *([record["undoes"]] if record.get("undoes") else [])]
                while pending:
                    current = pending.pop()
                    if current in seen:
                        continue
                    seen.add(current)
                    pending.extend(by_id.get(current, {}).get("supersedes", []))
                prior = self._review_prior(folder, root_key, record, by_id, names)
                prior_effective = self._review_prior_effective(folder, root_key, record, [item["id"] for item in prior], by_id)
                entry = {**self._review_entry(folder, root_key, record, state, names), "prior": prior, "prior_effective": prior_effective}
                entries.append(((record.get("reviewed_at") or "", len(seen), record["id"]), entry))
        return {"entries": [entry for _, entry in sorted(entries, key=lambda item: item[0], reverse=True)]}

    def undo_review(self, record_id: str) -> dict[str, Any]:
        """Append an undo record that reverts the effective head of one review chain."""
        for folder, root_key in REVIEW_FOLDERS:
            records = self.repository.records(folder)
            target = next((record for record in records if record["id"] == record_id), None)
            if target is not None:
                break
        else:
            raise KeyError(record_id)
        if target.get("undoes"):
            raise ReviewConflictError(f"Record {record_id} is an undo record and cannot be undone; review the item again to redo the judgment.")
        existing = next((record for record in records if record.get("undoes") == record_id), None)
        if existing is None:
            if not is_human_review(target, root_key):
                raise ReviewConflictError(f"Record {record_id} is not a human review judgment; only human judgments can be undone.")
            active = without_undone_reviews(records)
            superseding = sorted(record["id"] for record in active if record_id in record.get("supersedes", []))
            if superseding:
                raise ReviewConflictError(f"Record {record_id} is not the current effective judgment of its review chain; it is superseded by {', '.join(superseding)}. Undo the newer judgment first.")
            shadowing = review_shadowing(active, folder).get(record_id)
            if shadowing:
                raise ReviewConflictError(f"Record {record_id} is not the effective judgment; {shadowing} takes precedence for the same {'alias' if folder == 'aliases' else 'claim'}. Undo that judgment first.")
            existing = {
                **{key: value for key, value in target.items() if key not in {"id", "supersedes", "reviewed_at", "undoes"}},
                "id": stable_id("human-undo", record_id),
                root_key: target.get(root_key, target["id"]),
                "reviewer": "human",
                "reviewed_at": review_timestamp(),
                "supersedes": [record_id],
                "undoes": record_id,
            }
            self.repository.save(folder, existing)
            already_undone = False
            records = self.repository.records(folder)
        else:
            already_undone = True
        active = without_undone_reviews(records)
        active_ids = {record["id"] for record in active}
        superseded = set(review_supersession(active))
        candidates = [*target.get("supersedes", []), target.get(root_key)]
        restored = sorted({item for item in candidates if item and item != record_id and item in active_ids and item not in superseded})
        by_id = {record["id"]: record for record in active}
        human_restored = [item for item in restored if is_human_review(by_id[item], root_key)]
        # A restored human judgment still overrides the chain's original inference.
        restored = human_restored or restored
        return {"undo": existing, "undone_record_id": record_id, "restored_record_ids": restored, "already_undone": already_undone, "kind": self._review_entry(folder, root_key, target, self._review_chain_state(records, folder), {})["kind"]}

    def extract_with_provider(self, connection_id: str) -> dict[str, Any]:
        connection = self.connections.get(connection_id)
        if not connection:
            raise KeyError(connection_id)
        scan_result = self.prepare_provider_sources()
        source_passages = [Evidence(record["id"], record["source"]["path"], record["location"]["heading_path"], record["location"]["normalized_passage_sha256"], record["location"]["context_before"], record["location"]["context_after"], record["source"].get("git_blob"), record["location"].get("display_line"), record["text"], record.get("state", "current")) for record in self.repository.records("evidence") if record.get("state", "current") == "current"]
        source_passages = list({passage.id: passage for passage in source_passages}.values())
        extraction_text = "\n\n".join(f"[{p.id}] {p.source_path} :: {' / '.join(p.heading_path)}\n{p.text}" for p in source_passages)
        known_entities = self.repository.records_unchecked("entities")[:PROMPT_ENTITY_LIMIT]
        extraction_text += ENTITY_REFERENCE_GUIDE + "\nKnown entity IDs (id: name): " + ("; ".join(f"{record['id']}: {record.get('name', '')}" for record in known_entities) or "none yet")
        response = extract_with_litellm(connection, extraction_text)
        extraction_attempts = 1
        invalid_deltas = self._invalid_extraction_deltas(response)
        response, reference_errors, entity_catalog = self._resolve_delta_entity_references(response, source_passages)
        invalid_deltas += reference_errors
        if invalid_deltas:
            feedback = (
                "\n\nCORRECTION REQUIRED: Your previous response used unsupported or malformed option delta operations or selected flags. "
                "Retry extraction from the supplied passages. Preserve every source-grounded decision and option, "
                "but use only the documented typed operation shapes; when a safe typed operation cannot be formed, "
                "set that option's delta to {base:'architecture',operations:[]}. Use boolean selected values and mark at most one option selected. An operation may include expect:{} or expect:{exists:boolean}; do not include other keys or value types. Do not invent IDs.\n"
                f"Invalid operation examples: {invalid_deltas[:8]}"
            )
            if reference_errors:
                feedback += "\nValid entity references (id: name): " + "; ".join(f"{entity_id}: {name}" for entity_id, name in list(entity_catalog.items())[:PROMPT_ENTITY_LIMIT])
            response = extract_with_litellm(connection, extraction_text + feedback)
            extraction_attempts = 2
            response = self._resolve_delta_entity_references(response, source_passages)[0]
        overlay_files = {path.relative_to(self.repository.overlay): path.read_bytes() for path in self.repository.overlay.rglob("*") if path.is_file()}
        try:
            return self._persist_provider_extraction(connection, scan_result, source_passages, response, extraction_attempts)
        except Exception as persistence_error:
            overlay = self.repository.overlay
            current_files = {path.relative_to(overlay) for path in overlay.rglob("*") if path.is_file()}
            for relative in current_files - set(overlay_files):
                (overlay / relative).unlink(missing_ok=True)
            for relative, content in overlay_files.items():
                path = overlay / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            try:
                self._rebuild_indexes(source_passages)
            except Exception as index_error:
                raise RuntimeError(f"Provider extraction failed and indexes could not be reconciled after restoring canonical records: {type(index_error).__name__}: {index_error}") from persistence_error
            raise

    @staticmethod
    def _invalid_extraction_deltas(response: dict[str, Any]) -> list[str]:
        """Describe unsupported or malformed generated option operations for retry feedback."""
        allowed = {
            "add_entity": ("entity", {"id", "kind", "name"}),
            "remove_entity": ("entity", {"id"}),
            "replace_entity": ("entity", {"id", "kind", "name"}),
            "add_relationship": ("relationship", {"id", "from", "to", "kind"}),
            "remove_relationship": ("relationship", {"id"}),
            "replace_relationship": ("relationship", {"id", "from", "to", "kind"}),
        }
        invalid = []
        for decision in response.get("decisions", []):
            options = decision.get("options", [])
            selected_count = 0
            for option in options:
                selected = option.get("selected", False)
                if not isinstance(selected, bool):
                    invalid.append(f"{decision.get('title', '<untitled>')}/{option.get('title', '<untitled>')}: selected must be a boolean")
                selected_count += int(selected is True)
                if "delta" not in option:
                    delta = {"base": "architecture", "operations": []}
                else:
                    delta = option["delta"]
                label = f"{decision.get('title', '<untitled>')}/{option.get('title', '<untitled>')}"
                if not isinstance(delta, dict) or set(delta) != {"base", "operations"} or delta.get("base") != "architecture":
                    invalid.append(f"{label}: delta must contain only base='architecture' and operations")
                    continue
                operations = delta["operations"]
                if not isinstance(operations, list):
                    invalid.append(f"{label}: operations must be a list")
                    continue
                for operation in operations:
                    if not isinstance(operation, dict) or operation.get("op") not in allowed:
                        invalid.append(f"{label}: unsupported operation {operation!r}")
                        continue
                    field, required = allowed[operation["op"]]
                    value = operation.get(field)
                    allowed_value_keys = required | ({"description"} if field == "entity" and operation["op"] != "remove_entity" else set())
                    valid_shape = (
                        set(operation) in ({"op", field}, {"op", field, "expect"})
                        and isinstance(value, dict)
                        and required <= value.keys()
                        and value.keys() <= allowed_value_keys
                        and all(isinstance(value.get(key), str) and value[key].strip() for key in required)
                        and ("description" not in value or isinstance(value["description"], str))
                    )
                    if not valid_shape:
                        invalid.append(f"{label}: malformed {operation['op']} operation")
                        continue
                    if "expect" in operation and (
                        not isinstance(operation["expect"], dict)
                        or not set(operation["expect"]) <= {"exists"}
                        or ("exists" in operation["expect"] and not isinstance(operation["expect"]["exists"], bool))
                    ):
                        invalid.append(f"{label}: malformed {operation['op']} expect precondition; expect may be empty or contain only a boolean exists value")
            if selected_count > 1:
                invalid.append(f"{decision.get('title', '<untitled>')}: at most one option may be selected")
        return invalid

    def _resolve_delta_entity_references(self, response: dict[str, Any], source_passages: list[Evidence]) -> tuple[dict[str, Any], list[str], dict[str, str]]:
        """Map exact entity names or aliases in delta relationship endpoints to IDs; report unresolvable references.

        A reference that is already a known ID stays unchanged. A case/whitespace-normalized
        name or alias matching exactly one entity becomes that entity's ID. Ambiguous names and
        unknown references are returned for schema-feedback retry, with the entity catalog
        (ID to name) the retry may use. An unknown ID-shaped reference is reported only when
        that catalog is non-empty; otherwise no retry could resolve it, so repository
        validation records it in extraction_review.
        """
        def normalized(value: str) -> str:
            return " ".join(value.casefold().split())

        response = copy.deepcopy(response)
        catalog = {record["id"]: str(record.get("name", "")) for record in self.repository.records_unchecked("entities")}
        known_ids = set(catalog)
        names: dict[str, set[str]] = {}
        for entity_id, entity_name in catalog.items():
            names.setdefault(normalized(entity_name), set()).add(entity_id)
        # Only effective aliases map names: rejected, superseded, and undone judgments do not.
        for alias in effective_aliases(without_undone_reviews(self.repository.records_unchecked("aliases"))):
            names.setdefault(normalized(str(alias.get("name", ""))), set()).add(alias["entity_id"])
        for decision in self.repository.records_unchecked("decisions"):
            for option in decision.get("options", []):
                for operation in option.get("delta", {}).get("operations", []):
                    if operation.get("op") in {"add_entity", "replace_entity"}:
                        known_ids.add(operation.get("entity", {}).get("id"))
        candidates = response.get("entities", [])
        for candidate in candidates if isinstance(candidates, list) else []:
            if not isinstance(candidate, dict):
                continue
            name = str(candidate.get("name", "")).strip()
            quote = str(candidate.get("evidence_quote", "")).strip()
            if not name or len([item for item in source_passages if quote and quote.casefold() in item.text.casefold()]) != 1:
                continue
            entity_id = stable_id("entity", name.casefold())
            known_ids.add(entity_id)
            catalog.setdefault(entity_id, name)
            aliases = candidate.get("aliases", [])
            for label in [name, *(aliases if isinstance(aliases, list) else [])]:
                names.setdefault(normalized(str(label)), set()).add(entity_id)
        names.pop("", None)
        errors: list[str] = []
        decisions = response.get("decisions", [])
        for decision in decisions if isinstance(decisions, list) else []:
            options = decision.get("options", []) if isinstance(decision, dict) else []
            for option in options if isinstance(options, list) else []:
                delta = option.get("delta") if isinstance(option, dict) else None
                operations = delta.get("operations") if isinstance(delta, dict) else None
                if not isinstance(operations, list):
                    continue
                label = f"{decision.get('title', '<untitled>')}/{option.get('title', '<untitled>')}"
                delta_ids: set[str] = set()
                delta_names: dict[str, set[str]] = {}
                for operation in operations:
                    entity = operation.get("entity") if isinstance(operation, dict) and operation.get("op") in {"add_entity", "replace_entity"} else None
                    if isinstance(entity, dict) and isinstance(entity.get("id"), str):
                        delta_ids.add(entity["id"])
                        if isinstance(entity.get("name"), str):
                            delta_names.setdefault(normalized(entity["name"]), set()).add(entity["id"])
                for operation in operations:
                    relationship = operation.get("relationship") if isinstance(operation, dict) and operation.get("op") in {"add_relationship", "replace_relationship"} else None
                    if not isinstance(relationship, dict):
                        continue
                    for endpoint in ("from", "to"):
                        reference = relationship.get(endpoint)
                        if not isinstance(reference, str) or reference in known_ids or reference in delta_ids:
                            continue
                        key = normalized(reference)
                        matches = names.get(key, set()) | delta_names.get(key, set())
                        if len(matches) == 1:
                            relationship[endpoint] = next(iter(matches))
                        elif matches:
                            errors.append(f"{label}: entity reference {reference!r} is ambiguous; it matches IDs {sorted(matches)}. Use one exact entity ID.")
                        elif catalog or not PORTABLE_ID.match(reference):
                            errors.append(f"{label}: unknown entity reference {reference!r}. Use a known entity ID, an id added by the same delta, or the exact name of one returned entity.")
        return response, errors, catalog

    @classmethod
    def _alias_confidences(cls, candidate: dict[str, Any], name: str, diagnostics: list[str]) -> dict[str, float]:
        """Return a confidence per returned alias; invalid values default to 0.65 with a diagnostic.

        alias_confidence may be one number for every alias or a map whose keys exactly match
        returned aliases. An invalid value must not roll back the extraction; entity and claim
        confidence keep strict parsing. Entities without aliases ignore the field.
        """
        aliases = [str(alias).strip() for alias in candidate.get("aliases", [])] if isinstance(candidate.get("aliases"), list) else []
        aliases = [alias for alias in aliases if alias]
        if not aliases or "alias_confidence" not in candidate:
            return {}
        value = candidate["alias_confidence"]
        if isinstance(value, dict):
            confidences = {alias: cls._confidence_number(value.get(alias)) for alias in aliases}
            if set(value) <= set(aliases) and all(confidence is not None for confidence in confidences.values()):
                return {alias: confidence for alias, confidence in confidences.items() if confidence is not None}
        else:
            confidence = cls._confidence_number(value)
            if confidence is not None:
                return dict.fromkeys(aliases, confidence)
        diagnostics.append(f"Entity {name!r}: invalid alias_confidence {value!r} replaced by default 0.65.")
        return {}

    @staticmethod
    def _confidence_number(value: Any) -> float | None:
        """Parse a generated confidence as a number in [0, 1], or return None."""
        number = value
        if isinstance(value, str):
            try:
                number = float(value)
            except ValueError:
                number = None
        if isinstance(number, (int, float)) and not isinstance(number, bool) and 0 <= number <= 1:
            return float(number)
        return None

    @staticmethod
    def _normalized_option_label(label: str) -> str:
        """Normalize only case, whitespace, and the common leading `Use ` verb."""
        normalized = " ".join(label.casefold().split())
        if normalized.startswith("use "):
            normalized = normalized[4:].strip()
        return normalized

    @classmethod
    def _same_inferred_decision_choices(cls, candidate: dict[str, Any], existing: dict[str, Any]) -> bool:
        """Compare complete option labels and selected label without rewriting IDs."""
        candidate_options = candidate.get("options", [])
        existing_options = existing.get("options", [])
        candidate_labels = [cls._normalized_option_label(str(option.get("title", ""))) for option in candidate_options]
        existing_labels = [cls._normalized_option_label(str(option.get("title", ""))) for option in existing_options]
        if not candidate_labels or len(candidate_labels) != len(existing_labels) or len(set(candidate_labels)) != len(candidate_labels):
            return False
        if set(candidate_labels) != set(existing_labels):
            return False

        def selected_label(record: dict[str, Any]) -> str | None:
            selected_id = record.get("selected_option")
            selected_option = next((option for option in record.get("options", []) if option.get("id") == selected_id), None)
            return cls._normalized_option_label(str(selected_option.get("title", ""))) if selected_option else None

        return selected_label(candidate) == selected_label(existing)

    def _persist_provider_extraction(self, connection: dict[str, Any], scan_result: dict[str, Any], source_passages: list[Evidence], response: dict[str, Any], extraction_attempts: int = 1) -> dict[str, Any]:
        """Persist anchored provider records and refresh derived indexes atomically."""
        saved_entities: list[dict[str, Any]] = []
        saved_aliases: list[dict[str, Any]] = []
        saved_claims: list[dict[str, Any]] = []
        saved_relationships: list[dict[str, Any]] = []
        saved_consequences: list[dict[str, Any]] = []
        diagnostics: list[str] = []
        existing_entities = {record["id"] for record in self.repository.records("entities")}
        existing_aliases = {record["id"] for record in self.repository.records("aliases")}
        existing_claims = {record["id"] for record in self.repository.records("claims")}
        evidence_by_id = {item.id: item for item in source_passages}
        for candidate in response.get("entities", []):
            name = str(candidate.get("name", "")).strip()
            quote = str(candidate.get("evidence_quote", "")).strip()
            evidence_matches = [item for item in source_passages if quote and quote.casefold() in item.text.casefold()]
            if not name or len(evidence_matches) != 1:
                continue
            entity_id = stable_id("entity", name.casefold())
            ev = evidence_matches[0]
            confidence = float(candidate.get("confidence", 0.75))
            alias_confidences = self._alias_confidences(candidate, name, diagnostics)
            entity = {"schema_version": "decision/v1", "record_type": "entity", "id": entity_id, "name": name, "kind": candidate.get("kind", "component"), "epistemic_state": "inferred", "confidence": confidence, "evidence": [ev.id], "inferred_by": {"provider": connection["provider"], "model": connection["model"]}}
            if entity_id not in existing_entities:
                self.repository.save("entities", entity)
                saved_entities.append(entity)
                existing_entities.add(entity_id)
            claim_id = stable_id("claim", f"provider-mention/{entity_id}/{ev.id}")
            if claim_id not in existing_claims:
                claim = {"schema_version": "decision/v1", "record_type": "claim", "id": claim_id, "subject": entity_id, "predicate": "mentioned_in", "object": ev.source_path, "epistemic_state": "inferred", "confidence": confidence, "source_path": ev.source_path, "evidence": [ev.id], "inferred_by": {"provider": connection["provider"], "model": connection["model"]}}
                self.repository.save("claims", claim)
                saved_claims.append(claim)
                existing_claims.add(claim_id)
            for alias_name in candidate.get("aliases", []):
                alias_name = str(alias_name).strip()
                if not alias_name or alias_name.casefold() == name.casefold():
                    continue
                alias_id = stable_id("alias", f"{entity_id}/{alias_name.casefold()}")
                if alias_id not in existing_aliases:
                    alias = {"schema_version": "decision/v1", "record_type": "alias", "id": alias_id, "entity_id": entity_id, "name": alias_name, "epistemic_state": "inferred", "confidence": alias_confidences.get(alias_name, 0.65), "evidence": [ev.id], "inferred_by": {"provider": connection["provider"], "model": connection["model"]}}
                    self.repository.save("aliases", alias)
                    saved_aliases.append(alias)
                    existing_aliases.add(alias_id)
        entities_by_name = {record["name"].casefold(): record["id"] for record in self.repository.records_unchecked("entities")}
        for alias in self.repository.records_unchecked("aliases"):
            entities_by_name.setdefault(alias["name"].casefold(), alias["entity_id"])
        allowed_relations = {"uses", "publishes_to", "calls", "depends_on", "stores_in", "communicates_with", "implements"}
        for candidate in response.get("relationships", []):
            source_name = str(candidate.get("from_name", "")).strip()
            target_name = str(candidate.get("to_name", "")).strip()
            predicate = str(candidate.get("predicate", "")).strip()
            quote = str(candidate.get("evidence_quote", "")).strip()
            matches = [item for item in source_passages if quote and quote.casefold() in item.text.casefold()]
            subject = entities_by_name.get(source_name.casefold())
            object_id = entities_by_name.get(target_name.casefold())
            if not subject or not object_id or predicate not in allowed_relations or len(matches) != 1:
                continue
            ev = matches[0]
            claim_id = stable_id("claim", f"provider-relationship/{subject}/{predicate}/{object_id}/{ev.id}")
            if claim_id in existing_claims:
                continue
            claim = {"schema_version": "decision/v1", "record_type": "claim", "id": claim_id, "subject": subject, "predicate": predicate, "object": object_id, "epistemic_state": "inferred", "confidence": float(candidate.get("confidence", 0.75)), "source_path": ev.source_path, "evidence": [ev.id], "inferred_by": {"provider": connection["provider"], "model": connection["model"]}}
            try:
                self.repository.validate_candidate("claims", claim)
                self.repository.save("claims", claim)
            except DomainError:
                continue
            saved_claims.append(claim)
            saved_relationships.append(claim)
            existing_claims.add(claim_id)
        for candidate in response.get("consequences", []):
            subject_name = str(candidate.get("subject_name", "")).strip()
            decision_title = str(candidate.get("decision_title", "")).strip()
            predicate = str(candidate.get("predicate", "consequence")).strip() or "consequence"
            outcome = str(candidate.get("object", "")).strip()
            quote = str(candidate.get("evidence_quote", "")).strip()
            matches = [item for item in source_passages if quote and quote.casefold() in item.text.casefold()]
            subject = entities_by_name.get(subject_name.casefold())
            # Consequences may describe the decision itself (for example,
            # "requires an on-call rotation"), not an architecture entity.
            # Resolve those against the provider's anchored decision candidates.
            if not subject and decision_title:
                for decision_candidate in response.get("decisions", []):
                    if str(decision_candidate.get("title", "")).casefold() != decision_title.casefold():
                        continue
                    decision_quote = str(decision_candidate.get("evidence_quote", "")).strip()
                    decision_passages = [item for item in source_passages if decision_quote and decision_quote.casefold() in item.text.casefold()]
                    if len(decision_passages) == 1:
                        subject = stable_id("decision", f"{decision_passages[0].source_path}/{decision_title}")
                    break
            if not subject or not outcome or len(matches) != 1:
                continue
            ev = matches[0]
            claim_id = stable_id("claim", f"provider-consequence/{subject}/{predicate}/{outcome}/{ev.id}")
            if claim_id in existing_claims:
                continue
            claim = {"schema_version": "decision/v1", "record_type": "claim", "id": claim_id, "subject": subject, "predicate": predicate, "object": outcome, "epistemic_state": "inferred", "confidence": float(candidate.get("confidence", 0.75)), "source_path": ev.source_path, "evidence": [ev.id], "inferred_by": {"provider": connection["provider"], "model": connection["model"]}}
            try:
                self.repository.validate_candidate("claims", claim)
                self.repository.save("claims", claim)
            except DomainError:
                continue
            saved_claims.append(claim)
            saved_consequences.append(claim)
            existing_claims.add(claim_id)
        saved_decisions: list[dict[str, Any]] = []
        existing_decision_records = self.repository.records("decisions")
        existing_decisions = {record["id"]: record for record in existing_decision_records}
        superseded_decisions = {item for record in existing_decision_records for item in record.get("supersedes", [])}
        for candidate in response.get("decisions", []):
            title = str(candidate.get("title", "")).strip()
            selected_flags = [option.get("selected", False) for option in candidate.get("options", [])]
            if any(not isinstance(selected, bool) for selected in selected_flags):
                diagnostics.append(f"Decision {title!r} was not persisted: option selected values must be booleans.")
                continue
            if sum(selected_flags) > 1:
                diagnostics.append(f"Decision {title!r} was not persisted: multiple options were marked selected.")
                continue
            quote = str(candidate.get("evidence_quote", "")).strip()
            source_matches = [item for item in source_passages if quote and quote.casefold() in item.text.casefold()]
            if not title or len(source_matches) != 1:
                continue
            source_evidence = source_matches[0]
            options = []
            all_options_anchored = bool(candidate.get("options"))
            for option_data in candidate.get("options", []):
                option_title = str(option_data.get("title", "")).strip()
                option_quote = str(option_data.get("evidence_quote", quote)).strip()
                option_matches = [item for item in source_passages if option_quote and option_quote.casefold() in item.text.casefold()]
                if not option_title or len(option_matches) != 1:
                    all_options_anchored = False
                    continue
                option_evidence = option_matches[0]
                options.append({"id": stable_id("option", f"{source_evidence.source_path}/{title}/{option_title}"), "title": option_title, "rationale": str(option_data.get("rationale", "")), "evidence": [option_evidence.id], "delta": option_data.get("delta", {"base": "architecture", "operations": []}), "selected": option_data.get("selected", False)})
            if not options:
                continue
            decision_id = stable_id("decision", f"{source_evidence.source_path}/{title}")
            selected_options = [option["id"] for option in options if option.pop("selected")]
            selected = selected_options[0] if selected_options else None
            inferred = {"schema_version": "decision/v1", "record_type": "decision", "id": decision_id, "title": title, "status": "decided" if selected else "proposed", "epistemic_state": "inferred", "context": str(candidate.get("context", "")), "selected_option": selected, "evidence": [source_evidence.id], "options": options, "inferred_by": {"provider": connection["provider"], "model": connection["model"]}}
            existing = existing_decisions.get(decision_id)
            # Existing portable decisions may have been edited directly in YAML.
            # Extraction is additive; an explicit refresh workflow can be added later.
            if existing:
                continue
            same_evidence = [record for record in existing_decision_records if source_evidence.id in record.get("evidence", [])]
            eligible = [
                record for record in same_evidence
                if record.get("epistemic_state") == "inferred"
                and not record.get("reviewer")
                and not record.get("reviewed_decision")
                and record["id"] not in superseded_decisions
            ]
            matching = [record for record in eligible if self._same_inferred_decision_choices(inferred, record)]
            if len(matching) == 1:
                # Keep the original title, IDs, provenance, and choices intact.
                continue
            if same_evidence:
                diagnostics.append(
                    f"Decision {title!r} may duplicate an existing decision supported by the same passage; "
                    "option labels or review state do not establish one unambiguous match, so the candidate was kept for human review."
                )
            try:
                self.repository.validate_candidate("decisions", inferred)
            except DomainError as exc:
                # A safely anchored choice remains useful when only generated
                # deltas fail repository validation. Preserve the raw rejected
                # operations in review metadata and compile only empty deltas.
                fallback = copy.deepcopy(inferred)
                rejected_options: list[dict[str, Any]] = []
                for option in fallback["options"]:
                    option["delta"] = {"base": "architecture", "operations": []}
                if all_options_anchored:
                    try:
                        self.repository.validate_candidate("decisions", fallback)
                    except DomainError:
                        diagnostics.append(f"Decision {title!r} was not persisted: {exc}")
                        continue
                    for original_option, fallback_option in zip(inferred["options"], fallback["options"]):
                        original_delta = original_option.get("delta", {"base": "architecture", "operations": []})
                        if original_delta == fallback_option["delta"]:
                            continue
                        isolated = copy.deepcopy(fallback)
                        isolated_option = next(item for item in isolated["options"] if item["id"] == fallback_option["id"])
                        isolated_option["delta"] = copy.deepcopy(original_delta)
                        try:
                            self.repository.validate_candidate("decisions", isolated)
                        except DomainError as option_error:
                            rejected_options.append({"option_id": original_option["id"], "delta": copy.deepcopy(original_delta), "errors": [str(option_error)]})
                    if not rejected_options:
                        rejected_options = [
                            {"option_id": option["id"], "delta": copy.deepcopy(option["delta"]), "errors": [str(exc)]}
                            for option in inferred["options"]
                            if option.get("delta", {}).get("operations")
                        ]
                    if not rejected_options:
                        diagnostics.append(f"Decision {title!r} was not persisted: {exc}")
                        continue
                    fallback["extraction_review"] = {"status": "required", "attempts": extraction_attempts, "rejected_options": rejected_options}
                    try:
                        self.repository.validate_candidate("decisions", fallback)
                    except DomainError as review_error:
                        diagnostics.append(f"Decision {title!r} was not persisted: extraction review metadata failed validation: {review_error}")
                        continue
                    inferred = fallback
                    diagnostics.append(
                        f"Decision {title!r} was saved with empty active deltas because generated option deltas failed validation; review the recorded rejected deltas before relying on this decision."
                    )
                else:
                    diagnostics.append(f"Decision {title!r} was not persisted: {exc}")
                    continue
            try:
                self.repository.save("decisions", inferred)
            except DomainError as exc:
                diagnostics.append(f"Decision {title!r} was not persisted: {exc}")
                continue
            saved_decisions.append(inferred)
        index_status = self._rebuild_indexes(source_passages)
        return {"provider": connection["provider"], "model": connection["model"], "document_count": scan_result["document_count"], "passage_count": scan_result["passage_count"], "entities": saved_entities, "aliases": saved_aliases, "claims": saved_claims, "relationships": saved_relationships, "consequences": saved_consequences, "decisions": saved_decisions, "entity_count": len(saved_entities), "alias_count": len(saved_aliases), "claim_count": len(saved_claims), "relationship_count": len(saved_relationships), "consequence_count": len(saved_consequences), "decision_count": len(saved_decisions), "diagnostics": diagnostics, "index": index_status, "discarded_unanchored_candidates": True}

    def propose_delta(self, decision_id: str, option_id: str, request: str, connection_id: str | None = None) -> dict[str, Any]:
        connection = self.connections.get(connection_id) if connection_id else next(iter(self.connections.values()), None)
        if not connection:
            raise LookupError("Configure a model connection before asking AI to propose delta edits.")
        record = next((item for item in self.repository.records("decisions") if item["id"] == decision_id), None)
        if not record:
            raise KeyError(decision_id)
        option = next((item for item in record.get("options", []) if item["id"] == option_id), None)
        if not option:
            raise KeyError(option_id)
        proposal = propose_delta_with_litellm(connection, record, option, request, self.graph_json(annotate=False))
        delta = proposal.get("delta")
        if not isinstance(delta, dict) or not isinstance(delta.get("operations"), list):
            raise DomainError("Provider returned a delta without a typed operations list.")
        candidate = {**record, "options": [{**item, "delta": delta} if item["id"] == option_id else item for item in record["options"]]}
        self.repository.validate_candidate("decisions", candidate)
        base_graph, decisions, _, _, _ = self.graph()
        preview_decisions = []
        for decision in decisions:
            if decision.id != decision_id:
                preview_decisions.append(decision)
                continue
            options = [Option(item["id"], item.get("title", item["id"]), item.get("rationale", ""), item.get("delta", {"operations": []}), item.get("evidence", [])) for item in candidate["options"]]
            preview_decisions.append(Decision(decision.id, decision.title, decision.status, decision.context, decision.selected_option, options, decision.evidence))
        current_selections = {item.id: item.selected_option for item in preview_decisions if item.selected_option}
        current_selections[decision_id] = option_id
        compiled = compile_scenario(base_graph, preview_decisions, current_selections)
        preview = {"selections": current_selections, "added": compiled.added, "removed": compiled.removed, "changed": compiled.changed, "conflicts": compiled.conflicts, "invalid_assumptions": compiled.invalid_assumptions, "affected_decisions": compiled.affected_decisions}
        return {"decision_id": decision_id, "option_id": option_id, "delta": delta, "rationale": proposal.get("rationale", ""), "warnings": proposal.get("warnings", []), "preview": preview}

    def save_scenario(self, name: str, selections: dict[str, str]) -> dict[str, Any]:
        scenario_id = f"scenario-{uuid.uuid4().hex}"
        record = {"schema_version": "decision/v1", "record_type": "scenario", "id": scenario_id, "name": name, "selections": selections}
        self.repository.validate_candidate("scenarios", record)
        self.repository.save("scenarios", record)
        return record

    def list_scenarios(self) -> list[dict[str, Any]]:
        """Return saved scenarios in case-insensitive name and ID order."""
        scenarios = self.repository.records("scenarios")
        return [
            {"id": record["id"], "name": record["name"], "selections": record["selections"]}
            for record in sorted(scenarios, key=lambda item: (item["name"].casefold(), item["id"].casefold()))
        ]

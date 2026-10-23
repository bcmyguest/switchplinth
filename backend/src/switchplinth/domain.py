"""Portable domain records and deterministic graph/scenario compilation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = "decision/v1"
EPISTEMIC_STATES = {"inferred", "confirmed", "rejected", "asserted"}
SUPPORTED_OPERATIONS = {"add_entity", "remove_entity", "replace_entity", "add_relationship", "remove_relationship", "replace_relationship"}
CAPABILITY_PREDICATES = frozenset({"requires_capability", "provides_capability", "lacks_capability"})
CAPABILITY_KIND = "capability"
# The libyaml safe loader when available; both build plain Python values only.
YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


class DomainError(ValueError):
    """Invalid or conflicting portable domain data."""


@dataclass
class Evidence:
    id: str
    source_path: str
    heading_path: list[str]
    passage_sha256: str
    context_before: str = ""
    context_after: str = ""
    git_blob: str | None = None
    display_line: int | None = None
    text: str = ""
    state: str = "current"


@dataclass
class Entity:
    id: str
    kind: str
    name: str
    description: str = ""


@dataclass
class Alias:
    id: str
    entity_id: str
    name: str
    epistemic_state: str = "inferred"
    confidence: float = 0.5
    evidence: list[str] = field(default_factory=list)


@dataclass
class Claim:
    id: str
    subject: str
    predicate: str
    object: str
    epistemic_state: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    source_path: str | None = None
    supersedes: list[str] = field(default_factory=list)


@dataclass
class Relationship:
    id: str
    source: str
    target: str
    kind: str
    claim_id: str | None = None


@dataclass
class Option:
    id: str
    title: str
    rationale: str
    delta: dict[str, Any]
    evidence: list[str] = field(default_factory=list)


@dataclass
class Decision:
    id: str
    title: str
    status: str
    context: str
    selected_option: str | None
    options: list[Option]
    evidence: list[str] = field(default_factory=list)


@dataclass
class Graph:
    entities: dict[str, Entity] = field(default_factory=dict)
    relationships: dict[str, Relationship] = field(default_factory=dict)


@dataclass
class ScenarioResult:
    graph: Graph
    added: list[str]
    removed: list[str]
    changed: list[str]
    conflicts: list[str]
    invalid_assumptions: list[str]
    affected_decisions: list[str]


def stable_id(prefix: str, value: str) -> str:
    """Return a deterministic portable ID for normalized content."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def normalize_passage(text: str) -> str:
    return " ".join(text.casefold().split())


def passage_hash(text: str) -> str:
    return hashlib.sha256(normalize_passage(text).encode("utf-8")).hexdigest()


def evidence_anchor(path: str, heading_path: list[str], text: str, before: str = "", after: str = "") -> Evidence:
    normalized_path = Path(path).as_posix()
    digest = passage_hash(text)
    identity = f"{normalized_path}\n{'/'.join(heading_path)}\n{digest}"
    return Evidence(stable_id("evidence", identity), normalized_path, heading_path, digest, before, after, text=text)


def validate_record(record: dict[str, Any], expected: str | None = None) -> None:
    """Validate portable records against strict common invariants."""
    if record.get("schema_version") != SCHEMA_VERSION:
        raise DomainError(f"Unsupported schema_version {record.get('schema_version')!r}; explicit migration required to {SCHEMA_VERSION}.")
    if expected and record.get("record_type") != expected:
        raise DomainError(f"Expected {expected} record, got {record.get('record_type')!r}.")
    if not ID_PATTERN.fullmatch(str(record.get("id", ""))):
        raise DomainError("Record id must be a non-empty stable slug.")
    state = record.get("epistemic_state")
    if state is not None and state not in EPISTEMIC_STATES:
        raise DomainError(f"Unknown epistemic state {state!r}.")
    confidence = record.get("confidence")
    if confidence is not None and not 0 <= float(confidence) <= 1:
        raise DomainError("confidence must be between 0 and 1.")
    if state == "inferred" and record.get("record_type") in {"claim", "alias"} and not record.get("evidence"):
        raise DomainError("Inferred claims and aliases require evidence.")
    if record.get("record_type") == "decision":
        option_ids = [x.get("id") for x in record.get("options", [])]
        if len(option_ids) != len(set(option_ids)):
            raise DomainError("Decision option IDs must be unique.")
        selected = record.get("selected_option")
        if selected is not None and selected not in option_ids:
            raise DomainError(f"Selected option {selected!r} is not declared by decision {record['id']}.")
        for option in record.get("options", []):
            for operation in option.get("delta", {}).get("operations", []):
                if not isinstance(operation, dict):
                    raise DomainError("Delta operations must be mappings.")
                if operation.get("op") not in SUPPORTED_OPERATIONS:
                    raise DomainError(f"Unsupported delta operation {operation.get('op')!r}.")


def load_yaml(path: Path, expected: str | None = None) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        record = yaml.load(stream, Loader=YAML_LOADER)  # noqa: S506 - a safe loader
    if not isinstance(record, dict):
        raise DomainError(f"{path}: record must be a YAML mapping.")
    validate_record(record, expected)
    return record


def without_undone_reviews(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop undo control records and the human judgments they undo.

    An undone judgment's ``supersedes`` list no longer applies, so the prior
    judgment or original inference becomes effective again. Files stay intact.
    """
    undone = {record["undoes"] for record in records if record.get("undoes")}
    return [record for record in records if not record.get("undoes") and record["id"] not in undone]


def entity_kinds(entity_records: list[dict[str, Any]], decision_records: list[dict[str, Any]]) -> dict[str, str]:
    """Map every entity record and option-created entity ID to its kind."""
    kinds = {
        str(operation["entity"]["id"]): str(operation["entity"].get("kind", "component"))
        for decision in decision_records
        for option in decision.get("options", [])
        for operation in option.get("delta", {}).get("operations", [])
        if operation.get("op") in {"add_entity", "replace_entity"} and isinstance(operation.get("entity"), dict) and operation["entity"].get("id")
    }
    kinds.update({str(record["id"]): str(record.get("kind", "component")) for record in entity_records})
    return kinds


def validate_capability_endpoints(claim: dict[str, Any], kinds: dict[str, str]) -> None:
    """A capability claim links a known non-capability entity to a known entity of kind ``capability``.

    ``kinds`` comes from ``entity_kinds``, so either endpoint may be an entity
    record or an option-created entity (a scenario-only resource can provide or
    lack a capability).
    """
    subject, object_id = claim.get("subject"), claim.get("object")
    if subject not in kinds:
        raise DomainError(f"Capability claim {claim['id']} subject {subject} is not a known entity.")
    if kinds[subject] == CAPABILITY_KIND:
        raise DomainError(f"Capability claim {claim['id']} subject {subject} must not be a capability entity.")
    if kinds.get(object_id) != CAPABILITY_KIND:
        raise DomainError(f"Capability claim {claim['id']} object {object_id} must be a known entity of kind {CAPABILITY_KIND}.")


def effective_claims(claims: list[Claim]) -> list[Claim]:
    """Return active claims, with human records suppressing same propositions' inference."""
    superseded = {superseded_id for claim in claims for superseded_id in claim.supersedes}
    active_human = [c for c in claims if c.epistemic_state in {"confirmed", "asserted", "rejected"} and c.id not in superseded]
    human = {(c.subject, c.predicate, c.object): c for c in active_human}
    result = []
    for claim in claims:
        if claim.id in superseded:
            continue
        proposition = (claim.subject, claim.predicate, claim.object)
        judgment = human.get(proposition)
        if judgment:
            if claim.id == judgment.id and judgment.epistemic_state in {"confirmed", "asserted"}:
                result.append(claim)
            continue
        result.append(claim)
    return result


def identity_projection(entities: dict[str, Entity], claims: list[Claim]) -> dict[str, list[dict[str, Any]]]:
    """Project human identity judgments into groups and review conflicts."""
    superseded = {claim_id for claim in claims for claim_id in claim.supersedes}
    judgments = [
        claim for claim in claims
        if claim.id not in superseded
        and claim.predicate == "same_entity_as"
        and claim.epistemic_state in {"confirmed", "asserted", "rejected"}
        and claim.subject in entities and claim.object in entities
    ]
    pair_claims: dict[tuple[str, str], list[Claim]] = {}
    for claim in judgments:
        pair_claims.setdefault(tuple(sorted((claim.subject, claim.object))), []).append(claim)

    positive_pairs: set[tuple[str, str]] = set()
    rejected_pairs: set[tuple[str, str]] = set()
    conflicts: list[dict[str, Any]] = []
    for pair, pair_judgments in sorted(pair_claims.items()):
        positive = [claim for claim in pair_judgments if claim.epistemic_state in {"confirmed", "asserted"}]
        rejected = [claim for claim in pair_judgments if claim.epistemic_state == "rejected"]
        if positive:
            positive_pairs.add(pair)
        if rejected:
            rejected_pairs.add(pair)
        if positive and rejected:
            conflicts.append({"type": "conflicting_judgments", "entity_ids": list(pair), "claim_ids": sorted(claim.id for claim in [*positive, *rejected])})

    adjacency: dict[str, set[str]] = {entity_id: set() for entity_id in entities}
    for left, right in positive_pairs:
        adjacency[left].add(right)
        adjacency[right].add(left)
    components: list[set[str]] = []
    unseen = set(adjacency)
    while unseen:
        start = min(unseen)
        stack = [start]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(adjacency[current] - component)
        unseen -= component
        if len(component) > 1:
            components.append(component)

    blocked_components: set[frozenset[str]] = set()
    for component in components:
        for pair in sorted(rejected_pairs):
            if set(pair) <= component and pair not in positive_pairs:
                # A rejected pair contradicted by another confirmed path.
                path_claim_ids = sorted(
                    claim.id for claim in judgments
                    if claim.epistemic_state in {"confirmed", "asserted"}
                    and claim.subject in component and claim.object in component
                )
                conflicts.append({"type": "rejected_transitive_path", "entity_ids": list(pair), "component_entity_ids": sorted(component), "claim_ids": sorted({*(claim.id for claim in pair_claims[pair]), *path_claim_ids})})
                blocked_components.add(frozenset(component))
    conflicted_ids = {entity_id for conflict in conflicts for entity_id in conflict.get("component_entity_ids", conflict["entity_ids"])}
    groups = [
        {"entity_ids": sorted(component)} for component in components
        if not (component & conflicted_ids) and frozenset(component) not in blocked_components
    ]
    return {"identity_groups": sorted(groups, key=lambda group: group["entity_ids"]), "identity_conflicts": conflicts}


def effective_aliases(aliases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    superseded = {superseded_id for alias in aliases for superseded_id in alias.get("supersedes", [])}
    active_human = [a for a in aliases if a.get("epistemic_state") in {"confirmed", "asserted", "rejected"} and a["id"] not in superseded]
    judgments = {(a["entity_id"], a["name"].casefold()): a for a in active_human}
    result = []
    for alias in aliases:
        if alias["id"] in superseded:
            continue
        key = (alias["entity_id"], alias["name"].casefold())
        judgment = judgments.get(key)
        if judgment:
            if alias["id"] == judgment["id"] and judgment.get("epistemic_state") in {"confirmed", "asserted"}:
                result.append(alias)
            continue
        result.append(alias)
    return result


def compile_scenario(base: Graph, decisions: list[Decision], selections: dict[str, str]) -> ScenarioResult:
    """Apply selected option deltas deterministically, reporting incompatible writes."""
    graph = Graph(base.entities.copy(), base.relationships.copy())
    added: list[str] = []
    removed: list[str] = []
    changed: list[str] = []
    conflicts: list[str] = []
    invalid: list[str] = []
    affected: set[str] = set()
    operations: dict[str, str] = {}
    by_id = {d.id: d for d in decisions}
    for decision_id, option_id in sorted(selections.items()):
        decision = by_id.get(decision_id)
        if not decision:
            conflicts.append(f"Unknown decision {decision_id}.")
            continue
        option = next((o for o in decision.options if o.id == option_id), None)
        if not option:
            conflicts.append(f"Decision {decision_id} has no option {option_id}.")
            continue
        affected.add(decision_id)
        for op in option.delta.get("operations", []):
            kind = op["op"]
            target_kind = "entity" if "entity" in kind else "relationship"
            payload = op.get(target_kind, {})
            target_id = payload.get("id")
            key = f"{target_kind}:{target_id}"
            if key in operations and operations[key] != decision_id:
                conflicts.append(f"Decisions {operations[key]} and {decision_id} both write {key}.")
                continue
            operations[key] = decision_id
            actual_exists = target_id in (graph.entities if target_kind == "entity" else graph.relationships)
            expected_exists = op.get("expect", {}).get("exists")
            if expected_exists is not None and bool(expected_exists) != actual_exists:
                conflicts.append(f"Precondition failed for {key}: expected exists={bool(expected_exists)}, got {actual_exists}.")
                continue
            if kind.endswith("entity"):
                entity_id = payload.get("id")
                if kind == "add_entity":
                    if entity_id in graph.entities:
                        conflicts.append(f"Cannot add existing entity {entity_id}.")
                    else:
                        graph.entities[entity_id] = Entity(**payload)
                        added.append(entity_id)
                elif kind == "remove_entity":
                    if entity_id not in graph.entities:
                        conflicts.append(f"Cannot remove missing entity {entity_id}.")
                    else:
                        del graph.entities[entity_id]
                        removed.append(entity_id)
                        for rid, rel in list(graph.relationships.items()):
                            if rel.source == entity_id or rel.target == entity_id:
                                del graph.relationships[rid]
                                removed.append(rid)
                else:
                    if entity_id not in graph.entities:
                        conflicts.append(f"Cannot replace missing entity {entity_id}.")
                    else:
                        graph.entities[entity_id] = Entity(**payload)
                        changed.append(entity_id)
            else:
                relation_id = payload.get("id")
                if kind == "add_relationship":
                    if relation_id in graph.relationships:
                        conflicts.append(f"Cannot add existing relationship {relation_id}.")
                    elif payload.get("from") not in graph.entities or payload.get("to") not in graph.entities:
                        invalid.append(f"Relationship {relation_id} references an entity outside the scenario graph.")
                    else:
                        graph.relationships[relation_id] = Relationship(relation_id, payload["from"], payload["to"], payload["kind"])
                        added.append(relation_id)
                elif kind == "remove_relationship":
                    if relation_id not in graph.relationships:
                        conflicts.append(f"Cannot remove missing relationship {relation_id}.")
                    else:
                        del graph.relationships[relation_id]
                        removed.append(relation_id)
                else:
                    if relation_id not in graph.relationships:
                        conflicts.append(f"Cannot replace missing relationship {relation_id}.")
                    elif payload.get("from") not in graph.entities or payload.get("to") not in graph.entities:
                        invalid.append(f"Relationship {relation_id} references an entity outside the scenario graph.")
                    else:
                        graph.relationships[relation_id] = Relationship(relation_id, payload["from"], payload["to"], payload["kind"])
                        changed.append(relation_id)
    removed_set = set(removed)
    selected_decisions = set(selections)
    for decision in decisions:
        if decision.id in selected_decisions:
            continue
        for option in decision.options:
            for op in option.delta.get("operations", []):
                target_kind = "entity" if "entity" in op["op"] else "relationship"
                payload = op.get(target_kind, {})
                referenced = {payload.get("id")}
                if target_kind == "relationship":
                    referenced.update({payload.get("from"), payload.get("to")})
                referenced.discard(None)
                invalid_refs = referenced & removed_set
                if invalid_refs:
                    affected.add(decision.id)
                    invalid.append(f"Decision {decision.id} option {option.id} assumes removed architecture elements: {', '.join(sorted(invalid_refs))}.")
    return ScenarioResult(graph, sorted(set(added)), sorted(set(removed)), sorted(set(changed)), conflicts, sorted(set(invalid)), sorted(affected))

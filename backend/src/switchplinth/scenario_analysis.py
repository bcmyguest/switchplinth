"""Compare two resolved scenarios and trace what an option switch leaves dangling.

Pure functions over compiled domain graphs. Callers resolve each scenario with
the existing compiler (``compile_scenario`` through the service projection) and
pass the results here; this module never compiles deltas, reads files, or
touches HTTP, SQLite, Qdrant, or model providers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from switchplinth.domain import Decision, Entity, Graph, Relationship

IMPACT_MAX_DEPTH = 4
IMPACT_LIMITS = (
    "Relationship-based only: dependents are entities that reach a removed or replaced element over "
    "relationships in the before scenario (relationship source depends on target), up to max_depth hops. "
    "Every relationship kind is read in that one direction: communicates_with is not treated as "
    "symmetric, and implements makes the implementer depend on what it implements. Identity groups "
    "(same_entity_as) are not traversed; a dependent attached to another member of a confirmed group "
    "is missed. No code analysis, runtime data, or undeclared dependency is considered. 'rewired' is a "
    "heuristic: a lost edge counts as rewired when the after scenario gives the same source a new "
    "same-kind edge written by the newly selected option of a switched decision whose options "
    "reference the missing entity. It does not check that the option intended a replacement, and "
    "several lost same-kind edges can share one replacement."
)
RELATIONSHIP_WRITE_OPS = frozenset({"add_relationship", "replace_relationship"})


@dataclass(frozen=True)
class ResolvedScenario:
    """One compiled scenario: the full selection map, its graph, and its reported problems."""

    selections: dict[str, str]
    graph: Graph
    conflicts: list[str]
    invalid_assumptions: list[str]


def _entity_json(entity: Entity) -> dict[str, Any]:
    return {"id": entity.id, "kind": entity.kind, "name": entity.name, "description": entity.description}


def _relationship_json(relationship: Relationship) -> dict[str, Any]:
    return {"id": relationship.id, "from": relationship.source, "to": relationship.target, "kind": relationship.kind, "claim_id": relationship.claim_id}


def _entity_changed(before: Entity, after: Entity) -> bool:
    return (before.kind, before.name, before.description) != (after.kind, after.name, after.description)


def _relationship_changed(before: Relationship, after: Relationship) -> bool:
    return (before.source, before.target, before.kind) != (after.source, after.target, after.kind)


def _appeared(before: list[str], after: list[str]) -> dict[str, list[str]]:
    return {"appeared": sorted(set(after) - set(before)), "disappeared": sorted(set(before) - set(after))}


def _decision_references(decision: Decision) -> set[str]:
    """Every entity and relationship ID any option of this decision writes or connects."""
    referenced: set[str] = set()
    for option in decision.options:
        for operation in option.delta.get("operations", []):
            for key in ("entity", "relationship"):
                payload = operation.get(key)
                if isinstance(payload, dict):
                    referenced.update(str(payload[field]) for field in ("id", "from", "to") if payload.get(field))
    return referenced


def option_replacements(decisions: list[Decision], before_selections: dict[str, str], after_selections: dict[str, str]) -> dict[str, set[str]]:
    """Map each element a switched decision's options reference to the relationship IDs its after option writes.

    A lost edge to entity X may count as rewired only to a relationship that the
    after-selected option of a switched decision adds or replaces, where some
    option of that decision references X.
    """
    replacements: dict[str, set[str]] = {}
    for decision in decisions:
        option_id = after_selections.get(decision.id)
        if option_id is None or option_id == before_selections.get(decision.id):
            continue
        option = next((item for item in decision.options if item.id == option_id), None)
        written = {
            str(operation["relationship"]["id"])
            for operation in (option.delta.get("operations", []) if option else [])
            if operation.get("op") in RELATIONSHIP_WRITE_OPS and isinstance(operation.get("relationship"), dict) and operation["relationship"].get("id")
        }
        if written:
            for referenced in _decision_references(decision):
                replacements.setdefault(referenced, set()).update(written)
    return replacements


def _missing_endpoints(entity_id: str, before: Graph, after: Graph, allowed: dict[str, set[str]] | None) -> list[dict[str, Any]]:
    """Outgoing before-scenario relationships of ``entity_id`` whose target is absent after.

    An edge is ``rewired`` (a heuristic) when ``after`` gives the same source a
    relationship of the same kind to a target that source did not reach with
    that kind before (for example publishes_to Kafka stream -> publishes_to SQS
    stream); otherwise it is ``dangling``. When ``allowed`` is given, only
    ``allowed[missing target]`` count (see ``option_replacements``).
    """
    outgoing = sorted((rel for rel in before.relationships.values() if rel.source == entity_id), key=lambda item: item.id)
    after_outgoing = sorted((rel for rel in after.relationships.values() if rel.source == entity_id), key=lambda item: item.id)
    missing = []
    for relationship in outgoing:
        if relationship.target in after.entities:
            continue
        earlier_targets = {rel.target for rel in outgoing if rel.kind == relationship.kind}
        replacements = [
            {"relationship_id": rel.id, "to": rel.target}
            for rel in after_outgoing
            if rel.kind == relationship.kind and rel.target not in earlier_targets and (allowed is None or rel.id in allowed.get(relationship.target, ()))
        ]
        missing.append({
            "relationship_id": relationship.id,
            "kind": relationship.kind,
            "missing_entity_id": relationship.target,
            "status": "rewired" if replacements else "dangling",
            "rewired_to": replacements,
        })
    return missing


def _dependents(start: str, before: Graph, after: Graph, max_depth: int, seed: list[tuple[str, list[str]]], replacements: dict[str, set[str]] | None) -> tuple[list[dict[str, Any]], bool]:
    """Breadth-first walk against relationship direction from ``seed`` dependents.

    ``seed`` holds (entity_id, path) pairs at depth 1. Neighbours are visited in
    relationship-ID order, so the first-found (shortest) path is deterministic.
    """
    incoming: dict[str, list[Relationship]] = {}
    for relationship in sorted(before.relationships.values(), key=lambda item: item.id):
        if relationship.source != relationship.target:
            incoming.setdefault(relationship.target, []).append(relationship)
    visited = {start}
    frontier: list[tuple[str, list[str]]] = []
    for entity_id, path in seed:
        if entity_id not in visited:
            visited.add(entity_id)
            frontier.append((entity_id, path))
    found: list[tuple[str, int, list[str]]] = []
    depth = 1
    truncated = False
    while frontier:
        found.extend((entity_id, depth, path) for entity_id, path in frontier)
        following: list[tuple[str, list[str]]] = []
        for entity_id, path in frontier:
            for relationship in incoming.get(entity_id, []):
                if relationship.source in visited:
                    continue
                if depth >= max_depth:
                    truncated = True
                    continue
                visited.add(relationship.source)
                following.append((relationship.source, [relationship.source, relationship.id, *path]))
        frontier = following
        depth += 1
    dependents = []
    for entity_id, entity_depth, path in sorted(found, key=lambda item: (item[1], item[0])):
        entity = before.entities.get(entity_id)
        missing = _missing_endpoints(entity_id, before, after, replacements)
        dependents.append({
            "entity_id": entity_id,
            "name": entity.name if entity else entity_id,
            "depth": entity_depth,
            "path": path,
            "present_after": entity_id in after.entities,
            "points_at_missing": any(item["status"] == "dangling" for item in missing),
            "rewired": any(item["status"] == "rewired" for item in missing),
            "missing_endpoints": missing,
        })
    return dependents, truncated


def downstream_impact(before: Graph, after: Graph, max_depth: int = IMPACT_MAX_DEPTH, replacements: dict[str, set[str]] | None = None) -> dict[str, Any]:
    """List dependents of every element ``after`` removes or replaces relative to ``before``.

    Items are removed and replaced entities, then removed and replaced
    relationships whose endpoints both survive (a relationship removed with its
    endpoint entity is covered by that entity's item). Each dependent carries
    its depth, a path of alternating entity and relationship IDs ending at the
    item, whether it survives in ``after``, and its outgoing before-scenario
    relationships whose target is absent from ``after``, each marked
    ``rewired`` or ``dangling`` (see ``_missing_endpoints``). ``replacements``
    restricts rewiring per missing entity; callers pass ``option_replacements``.
    ``None`` accepts any new same-kind edge from the same source.
    """
    items: list[dict[str, Any]] = []
    for entity_id in sorted(before.entities):
        entity = before.entities[entity_id]
        if entity_id in after.entities and not _entity_changed(entity, after.entities[entity_id]):
            continue
        change = "replaced" if entity_id in after.entities else "removed"
        seed = [(relationship.source, [relationship.source, relationship.id, entity_id]) for relationship in sorted(before.relationships.values(), key=lambda item: item.id) if relationship.target == entity_id and relationship.source != entity_id]
        dependents, truncated = _dependents(entity_id, before, after, max_depth, seed, replacements)
        items.append({"type": "entity", "id": entity_id, "name": entity.name, "change": change, "dependents": dependents, "truncated": truncated})
    for relationship_id in sorted(before.relationships):
        relationship = before.relationships[relationship_id]
        if not {relationship.source, relationship.target} <= after.entities.keys():
            continue
        replacement = after.relationships.get(relationship_id)
        if replacement is not None and not _relationship_changed(relationship, replacement):
            continue
        change = "replaced" if replacement is not None else "removed"
        seed = [(relationship.source, [relationship.source, relationship.id, relationship.target])]
        dependents, truncated = _dependents(relationship.target, before, after, max_depth, seed, replacements)
        items.append({"type": "relationship", "id": relationship_id, "name": relationship.kind, "change": change, "dependents": dependents, "truncated": truncated})
    return {"basis": "before_scenario_relationships", "max_depth": max_depth, "limits": IMPACT_LIMITS, "items": items}


def diff_resolved_scenarios(before: ResolvedScenario, after: ResolvedScenario, decisions: list[Decision], max_depth: int = IMPACT_MAX_DEPTH) -> dict[str, Any]:
    """Describe how ``after`` differs from ``before``: records, problems, decisions, and impact."""
    entities: dict[str, list[dict[str, Any]]] = {"added": [], "removed": [], "changed": []}
    for entity_id in sorted(before.graph.entities.keys() | after.graph.entities.keys()):
        old, new = before.graph.entities.get(entity_id), after.graph.entities.get(entity_id)
        if old is None and new is not None:
            entities["added"].append(_entity_json(new))
        elif new is None and old is not None:
            entities["removed"].append(_entity_json(old))
        elif old is not None and new is not None and _entity_changed(old, new):
            entities["changed"].append({"id": entity_id, "before": _entity_json(old), "after": _entity_json(new)})
    relationships: dict[str, list[dict[str, Any]]] = {"added": [], "removed": [], "changed": []}
    for relationship_id in sorted(before.graph.relationships.keys() | after.graph.relationships.keys()):
        old_rel, new_rel = before.graph.relationships.get(relationship_id), after.graph.relationships.get(relationship_id)
        if old_rel is None and new_rel is not None:
            relationships["added"].append(_relationship_json(new_rel))
        elif new_rel is None and old_rel is not None:
            relationships["removed"].append(_relationship_json(old_rel))
        elif old_rel is not None and new_rel is not None and _relationship_changed(old_rel, new_rel):
            relationships["changed"].append({"id": relationship_id, "before": _relationship_json(old_rel), "after": _relationship_json(new_rel)})
    selection_changes = [
        {"decision_id": decision_id, "before_option": before.selections.get(decision_id), "after_option": after.selections.get(decision_id)}
        for decision_id in sorted(before.selections.keys() | after.selections.keys())
        if before.selections.get(decision_id) != after.selections.get(decision_id)
    ]
    changed_ids = {item["id"] for group in (entities, relationships) for items in group.values() for item in items}
    switched = {change["decision_id"] for change in selection_changes}
    affected = []
    for decision in sorted(decisions, key=lambda item: item.id):
        reasons = []
        if decision.id in switched:
            reasons.append("selection_changed")
        if _decision_references(decision) & changed_ids:
            reasons.append("options_reference_changed_elements")
        if reasons:
            affected.append({"id": decision.id, "title": decision.title, "reasons": reasons})
    return {
        "selections": {"before": dict(sorted(before.selections.items())), "after": dict(sorted(after.selections.items()))},
        "selection_changes": selection_changes,
        "entities": entities,
        "relationships": relationships,
        "conflicts": _appeared(before.conflicts, after.conflicts),
        "invalid_assumptions": _appeared(before.invalid_assumptions, after.invalid_assumptions),
        "affected_decisions": affected,
        "impact": downstream_impact(before.graph, after.graph, max_depth, option_replacements(decisions, before.selections, after.selections)),
    }

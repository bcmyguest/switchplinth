"""Deterministic input receipts for scenario, graph, search, and diff reads.

A receipt is a SHA-256 digest over canonical JSON (sorted keys, compact
separators, UTF-8) of the canonical `.decision/` records a read consumed, the
effective human review-chain heads, the evidence anchor hashes, the resolved
selection map, and any request parameters such as a search query. It never
depends on SQLite, Qdrant, timestamps taken at read time, dict order, or the
process, so recomputing it later answers "did the inputs change?".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from switchplinth.domain import without_undone_reviews

RECEIPT_ALGORITHM = "switchplinth-receipt/v1"
RECEIPT_FOLDERS = ("aliases", "claims", "decisions", "entities", "evidence", "relationships")
HUMAN_STATES = {"confirmed", "asserted", "rejected"}


def _json_default(value: Any) -> str:
    # yaml.safe_load turns unquoted ISO timestamps into date/datetime objects.
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Cannot canonicalize {type(value).__name__} in a receipt.")


def canonical_json(value: Any) -> str:
    """Serialize ``value`` the same way in every process: sorted keys, no whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_default)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _review_heads(records: Mapping[str, list[dict[str, Any]]]) -> list[list[str]]:
    """Unsuperseded, not-undone human judgments: the current head of each review chain."""
    heads = []
    for folder in ("aliases", "claims"):
        active = without_undone_reviews(list(records.get(folder, [])))
        superseded = {record_id for record in active for record_id in record.get("supersedes", [])}
        heads.extend(
            [folder, str(record["id"]), str(record["epistemic_state"])]
            for record in active
            if record.get("epistemic_state") in HUMAN_STATES and record["id"] not in superseded
        )
    return sorted(heads)


def _evidence_anchors(records: Mapping[str, list[dict[str, Any]]]) -> list[list[str]]:
    anchors = {
        (
            str(record["id"]),
            str(record.get("source", {}).get("path", "")),
            str(record.get("location", {}).get("normalized_passage_sha256", "")),
            str(record.get("state", "current")),
        )
        for record in records.get("evidence", [])
    }
    return [list(anchor) for anchor in sorted(anchors)]


def input_receipt(records: Mapping[str, list[dict[str, Any]]], selections: Mapping[str, Any], request: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return the receipt for a read over ``records`` (folder -> raw YAML records) and ``selections``.

    ``selections`` is echoed back as given; pass the resolved map (repository
    defaults merged with the request) so that an explicit default and an
    omitted one yield the same receipt. ``request`` holds extra inputs that
    shaped the result, such as ``{"query": ...}`` for search.
    """
    record_digests = sorted(
        [folder, str(record.get("id", "")), _digest(record)]
        for folder in RECEIPT_FOLDERS
        for record in records.get(folder, [])
    )
    components = {
        "records": _digest(record_digests),
        "review_heads": _digest(_review_heads(records)),
        "evidence_anchors": _digest(_evidence_anchors(records)),
        "selections": _digest(selections),
    }
    if request is not None:
        components["request"] = _digest(request)
    receipt = {
        "algorithm": RECEIPT_ALGORITHM,
        "digest": _digest({"algorithm": RECEIPT_ALGORITHM, "components": components}),
        "components": components,
        "record_count": len(record_digests),
        "selections": json.loads(canonical_json(selections)),
    }
    if request is not None:
        receipt["request"] = json.loads(canonical_json(request))
    return receipt

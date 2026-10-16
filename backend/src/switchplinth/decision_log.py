"""Derive Architecture log reasons from cited Markdown passages.

Pure and deterministic: depends only on domain dataclasses. Each derived
statement is an exact substring of one current evidence passage.

A rejection reason is a source-stated limitation of an option the record did
not select. It follows the record's `selected_option`, not a scenario preview,
and an undecided record has none. The rules are English heading and cue
heuristics: a `, but` clause counts only when it carries a limitation cue, and
the limitation-sentence fallback can still match a neutral sentence such as
"Cost is not a concern." No recall or precision is claimed beyond the
food-delivery fixture; label the output as derived from source.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from switchplinth.domain import Decision, Evidence

ALTERNATIVE_HEADING = re.compile(r"\b(alternative|considered)\b", re.I)
CONSEQUENCES_HEADING = re.compile(r"^consequences?$", re.I)
CONTRAST_CLAUSE = re.compile(r",\s+but\s+(.+)$", re.I)
CONTRAST_LIMITATION_CUE = re.compile(r"\b(would|not|cannot|can't|require[sd]?|needs?|harder|slower|risks?)\b", re.I)
LIMITATION_MARKERS = ("does not", "is not", "cannot", "would still need", "would require", "however")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class SourceStatement:
    text: str
    evidence_id: str


@dataclass(frozen=True)
class DecisionReasons:
    consequences: list[SourceStatement]
    rejection_reasons: dict[str, SourceStatement]


class _PassageIndex:
    """Current passages by ID and Consequences sections by owning section, built once per render."""

    def __init__(self, passages: Sequence[Evidence]) -> None:
        self.current = {item.id: item for item in passages if item.state == "current"}
        self.consequences: dict[tuple[str, tuple[str, ...]], list[Evidence]] = defaultdict(list)
        for item in self.current.values():
            if len(item.heading_path) > 1 and CONSEQUENCES_HEADING.match(item.heading_path[-1].strip()):
                self.consequences[(item.source_path, tuple(item.heading_path[:-1]))].append(item)


def decision_log_reasons(decisions: Sequence[Decision], passages: Sequence[Evidence]) -> dict[str, DecisionReasons]:
    """Derive reasons for every decision with one passage index; cost is linear in decisions plus passages."""
    index = _PassageIndex(passages)
    return {decision.id: _derive(decision, index) for decision in decisions}


def decision_reasons(decision: Decision, passages: Sequence[Evidence]) -> DecisionReasons:
    """Return source-stated rejection reasons for unselected options and the decision's consequences.

    Only current passages count. Options without a stated reason are omitted;
    nothing is invented for them, for the record's selected option, or for an
    undecided record.
    """
    return _derive(decision, _PassageIndex(passages))


def _derive(decision: Decision, index: _PassageIndex) -> DecisionReasons:
    return DecisionReasons(consequences=_consequences(decision, index), rejection_reasons=_rejection_reasons(decision, index.current))


def _rejection_reasons(decision: Decision, current: dict[str, Evidence]) -> dict[str, SourceStatement]:
    selected = next((option for option in decision.options if option.id == decision.selected_option), None)
    if selected is None:
        return {}
    shared = {*selected.evidence, *decision.evidence}
    reasons: dict[str, SourceStatement] = {}
    for option in decision.options:
        if option is selected:
            continue
        source = _alternative_passage(option.evidence, current, shared)
        reason = _stated_reason(source) if source else None
        if source and reason:
            reasons[option.id] = SourceStatement(reason, source.id)
    return reasons


def _last_heading(passage: Evidence) -> str:
    return passage.heading_path[-1] if passage.heading_path else ""


def _sentences(text: str) -> list[str]:
    return [sentence for sentence in SENTENCE_SPLIT.split(text.strip()) if sentence]


def _alternative_passage(evidence_ids: list[str], current: dict[str, Evidence], shared: set[str]) -> Evidence | None:
    """Prefer a cited alternative-headed passage; otherwise the first cited passage not shared with the choice or decision."""
    cited = [current[evidence_id] for evidence_id in evidence_ids if evidence_id in current]
    headed = next((item for item in cited if ALTERNATIVE_HEADING.search(_last_heading(item))), None)
    if headed:
        return headed
    return next((item for item in cited if item.id not in shared), None)


def _stated_reason(source: Evidence) -> str | None:
    sentences = _sentences(source.text)
    for sentence in sentences:
        match = CONTRAST_CLAUSE.search(sentence)
        if match and CONTRAST_LIMITATION_CUE.search(match.group(1)):
            return match.group(1)
    return next((sentence for sentence in sentences if any(marker in sentence.lower() for marker in LIMITATION_MARKERS)), None)


def _consequences(decision: Decision, index: _PassageIndex) -> list[SourceStatement]:
    """Consequences sections that are siblings of the decision's anchor passage in the same document."""
    anchor = index.current.get(decision.evidence[0]) if decision.evidence else None
    if anchor is None or not anchor.heading_path:
        return []
    owner = anchor.heading_path if len(anchor.heading_path) == 1 else anchor.heading_path[:-1]
    sections = index.consequences.get((anchor.source_path, tuple(owner)), [])
    return [SourceStatement(sentence, item.id) for item in sections for sentence in _sentences(item.text)]

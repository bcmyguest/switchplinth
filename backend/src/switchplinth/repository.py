"""Filesystem adapters for portable Markdown and YAML records."""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from switchplinth.domain import CAPABILITY_PREDICATES, DomainError, Evidence, entity_kinds, evidence_anchor, load_yaml, validate_capability_endpoints, validate_record

DEFAULT_IGNORES = {".git", ".venv", "venv", "node_modules", "dist", "build", "coverage", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".cache", ".decision", ".decision-cache", ".tasks"}
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
def source_is_included(source_path: str, includes: list[str] | set[str]) -> bool:
    """Return whether a configured source path matches a file or directory."""
    return any(source_path == item.rstrip("/") or source_path.startswith(item.rstrip("/") + "/") for item in includes)


def validate_extraction_review(record: dict[str, Any]) -> None:
    """Validate review metadata even when a project has an older overlay schema."""
    if "extraction_review" not in record:
        return
    bundled_schema = json.loads(Path(__file__).with_name("record-v1.schema.json").read_text(encoding="utf-8"))
    review_schema = bundled_schema["$defs"]["extraction_review"]
    errors = sorted(Draft202012Validator(review_schema).iter_errors(record["extraction_review"]), key=lambda error: list(error.path))
    if errors:
        raise DomainError(f"Invalid extraction_review: {errors[0].message}")


@functools.cache
def _bundled_record_schema() -> dict[str, Any]:
    """Load the bundled v1 record schema once; callers must not mutate it."""
    return json.loads(Path(__file__).with_name("record-v1.schema.json").read_text(encoding="utf-8"))


def validate_review_metadata(record: dict[str, Any]) -> None:
    """Validate additive review and connection fields against the bundled v1 schema."""
    fields = [field for field in ("reviewed_at", "undoes", "generation") if field in record]
    if not fields:
        return
    bundled_schema = _bundled_record_schema()
    for field in fields:
        errors = list(Draft202012Validator(bundled_schema["$defs"][field]).iter_errors(record[field]))
        if errors:
            raise DomainError(f"Invalid {field}: {errors[0].message}")
    if "undoes" in record and record.get("record_type") not in {"claim", "alias"}:
        raise DomainError("Only claim and alias review records may declare undoes.")
    if "generation" in record and record.get("record_type") != "model_connection":
        raise DomainError("Only model_connection records may declare generation.")


def discover_markdown(root: Path, excludes: set[str] | None = None, includes: list[str] | set[str] | None = None) -> list[Path]:
    user_ignores = excludes or set()
    configured_includes = includes or set()
    discovered = []
    for path in root.rglob("*.md"):
        relative = path.relative_to(root).as_posix()
        parts = set(path.relative_to(root).parts)
        if parts & user_ignores:
            continue
        default_ignored = parts & DEFAULT_IGNORES
        if default_ignored:
            # An explicit source include can opt into .tasks only. Other
            # generated and metadata directories remain excluded.
            if default_ignored != {".tasks"} or not source_is_included(relative, configured_includes):
                continue
        discovered.append(path)
    return sorted(discovered)


def passages(path: Path, root: Path) -> list[Evidence]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    heading_stack: list[str] = []
    chunks: list[tuple[list[str], list[str], int]] = []
    current: list[str] = []
    current_heading: list[str] = []
    current_line = 1
    for number, line in enumerate(lines, start=1):
        match = HEADING.match(line)
        if match:
            if current:
                chunks.append((current_heading, current, current_line))
                current = []
            level = len(match.group(1))
            heading_stack[:] = heading_stack[:level - 1]
            heading_stack.append(match.group(2))
            current_heading = heading_stack.copy()
            current_line = number + 1
        elif not line.strip():
            if current:
                chunks.append((current_heading, current, current_line))
                current = []
        else:
            if not current:
                current_line = number
            current.append(line.strip())
    if current:
        chunks.append((current_heading, current, current_line))
    output: list[Evidence] = []
    for index, (heading, chunk, line_no) in enumerate(chunks):
        passage = " ".join(chunk)
        if len(passage) < 20:
            continue
        before = " ".join(chunks[index - 1][1])[-160:] if index else ""
        after = " ".join(chunks[index + 1][1])[:160] if index + 1 < len(chunks) else ""
        anchor = evidence_anchor(path.relative_to(root).as_posix(), heading, passage, before, after)
        anchor.display_line = line_no
        anchor.git_blob = None
        output.append(anchor)
    return output


def source_identity(path: Path, root: Path) -> dict[str, str | None]:
    content = path.read_bytes()
    try:
        git_blob = subprocess.run(["git", "-C", str(root), "hash-object", str(path)], check=True, capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        git_blob = None
    return {"path": path.relative_to(root).as_posix(), "git_blob": git_blob or None, "content_sha256": hashlib.sha256(content).hexdigest()}


def relocate_evidence(previous: Evidence, current: list[Evidence]) -> Evidence:
    """Relocate exact passage first, then use heading/context score; ambiguity stays unresolved."""
    same_path = [item for item in current if item.source_path == previous.source_path]
    exact = [item for item in same_path if item.passage_sha256 == previous.passage_sha256]
    if len(exact) == 1:
        exact[0].id = previous.id
        return exact[0]
    candidates: list[tuple[int, Evidence]] = []
    for item in same_path:
        score = 0
        if item.heading_path == previous.heading_path:
            score += 3
        if previous.context_before and item.context_before and (previous.context_before in item.context_before or item.context_before in previous.context_before):
            score += 1
        if previous.context_after and item.context_after and (previous.context_after in item.context_after or item.context_after in previous.context_after):
            score += 1
        if score:
            candidates.append((score, item))
    candidates.sort(key=lambda x: x[0], reverse=True)
    if candidates and candidates[0][0] >= 4 and (len(candidates) == 1 or candidates[0][0] > candidates[1][0]):
        candidates[0][1].id = previous.id
        return candidates[0][1]
    return Evidence(previous.id, previous.source_path, previous.heading_path, previous.passage_sha256, previous.context_before, previous.context_after, previous.git_blob, previous.display_line, previous.text, "unresolved")


class PortableRepository:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.overlay = self.root / ".decision"
        if self.root.is_dir():
            self.bootstrap_overlay()

    def bootstrap_overlay(self) -> None:
        """Create portable v1 defaults for a newly opened Markdown repository."""
        schema_dir = self.overlay / "schema"
        schema_dir.mkdir(parents=True, exist_ok=True)
        schema_path = schema_dir / "record-v1.schema.json"
        if not schema_path.exists():
            bundled_schema = Path(__file__).with_name("record-v1.schema.json")
            schema_path.write_bytes(bundled_schema.read_bytes())
        config_path = self.overlay / "config.yaml"
        if not config_path.exists():
            config_path.write_text(
                "schema_version: decision/v1\nrecord_type: config\nid: project\n"
                "extraction:\n  mode: mock\n  ignore: [.git, .decision, .decision-cache, .venv, node_modules, dist, build, __pycache__, .pytest_cache, .mypy_cache, .ruff_cache, .tox, .cache]\n  include: []\n  max_candidates: 50\nconnections: []\n",
                encoding="utf-8",
            )
        instructions = self.overlay / "instructions.md"
        if not instructions.exists():
            instructions.write_text(
                "Use each document's own section names. Treat a decision as selected only when the source makes an outcome explicit. Cite a specific evidence passage for inferred claims and aliases. Keep ambiguous entity matches separate for human review.\n",
                encoding="utf-8",
            )

    def records(self, kind: str) -> list[dict[str, Any]]:
        directory = self.overlay / kind
        if not directory.exists():
            return []
        schema_path = self.overlay / "schema" / "record-v1.schema.json"
        schema = __import__("json").loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        result = []
        for path in sorted(directory.glob("*.yaml")):
            record = load_yaml(path)
            errors = sorted(validator.iter_errors(record), key=lambda e: list(e.path))
            if errors:
                raise DomainError(f"{path}: {errors[0].message}")
            validate_extraction_review(record)
            validate_review_metadata(record)
            result.append(record)
        if kind in {"entities", "evidence", "aliases", "claims", "relationships", "decisions", "scenarios", "connections", "agents"}:
            self.validate_references()
        return result

    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate project config without requiring source references to be current."""
        schema_path = self.overlay / "schema" / "record-v1.schema.json"
        schema = __import__("json").loads(schema_path.read_text(encoding="utf-8"))
        errors = sorted(Draft202012Validator(schema).iter_errors(config), key=lambda e: list(e.path))
        if errors:
            raise DomainError(f"{self.overlay / 'config.yaml'}: {errors[0].message}")

    def validate_references(self, override: tuple[str, dict[str, Any]] | None = None) -> None:
        """Validate portable references across all record families."""
        types = {"entities": "entity", "evidence": "evidence", "aliases": "alias", "claims": "claim", "relationships": "relationship", "decisions": "decision", "scenarios": "scenario", "connections": "model_connection", "agents": "agent_connection"}
        records: dict[str, list[dict[str, Any]]] = {kind: self.records_unchecked(kind) for kind in types}
        if override:
            folder, replacement = override
            current = next((index for index, row in enumerate(records[folder]) if row["id"] == replacement["id"]), None)
            if current is None:
                records[folder].append(replacement)
            else:
                records[folder][current] = replacement
        config_path = self.overlay / "config.yaml"
        if config_path.exists():
            self.validate_config(load_yaml(config_path))
        ids = {kind: {record["id"] for record in rows} for kind, rows in records.items()}
        option_entity_ids = {
            operation.get("entity", {}).get("id")
            for decision in records["decisions"]
            for option in decision.get("options", [])
            for operation in option.get("delta", {}).get("operations", [])
            if operation.get("op") in {"add_entity", "replace_entity"}
        }
        known_entity_ids = ids["entities"] | option_entity_ids
        for evidence in records["evidence"]:
            source_path = (self.root / evidence["source"]["path"]).resolve()
            if self.root not in source_path.parents and source_path != self.root:
                raise DomainError(f"Evidence {evidence['id']} source path escapes the repository.")
            if not source_path.is_file() and evidence.get("state", "current") != "unresolved":
                raise DomainError(f"Evidence {evidence['id']} references missing source {evidence['source']['path']}.")
            from switchplinth.domain import passage_hash
            if passage_hash(evidence["text"]) != evidence["location"]["normalized_passage_sha256"]:
                raise DomainError(f"Evidence {evidence['id']} passage hash does not match its text.")
        for alias in records["aliases"]:
            if alias.get("epistemic_state") == "inferred" and not alias.get("evidence"):
                raise DomainError(f"Inferred alias {alias['id']} requires evidence.")
        for entity in records["entities"]:
            if entity.get("epistemic_state") == "inferred" and not entity.get("evidence"):
                raise DomainError(f"Inferred entity {entity['id']} requires evidence.")
        for claim in records["claims"]:
            if claim.get("epistemic_state") == "inferred" and not claim.get("evidence"):
                raise DomainError(f"Inferred claim {claim['id']} requires evidence.")
        for row in records["aliases"]:
            if row["entity_id"] not in known_entity_ids:
                raise DomainError(f"Alias {row['id']} references missing entity {row['entity_id']}.")
            missing = set(row.get("evidence", [])) - ids["evidence"]
            if missing:
                raise DomainError(f"Alias {row['id']} references missing evidence: {', '.join(sorted(missing))}.")
        for folder in ("aliases", "claims"):
            for row in records[folder]:
                if row.get("undoes") and (row["undoes"] not in ids[folder] or row["undoes"] not in row.get("supersedes", [])):
                    raise DomainError(f"Undo record {row['id']} must supersede an existing {folder[:-1]} record it undoes.")
        for row in records["claims"]:
            missing = set(row.get("evidence", [])) - ids["evidence"]
            if missing:
                raise DomainError(f"Claim {row['id']} references missing evidence: {', '.join(sorted(missing))}.")
            if row.get("predicate") == "same_entity_as":
                subject, object_id = row.get("subject"), row.get("object")
                if subject == object_id:
                    raise DomainError(f"Identity claim {row['id']} must link two distinct entities.")
                endpoints = {entity["id"]: entity for entity in records["entities"]}
                if subject not in endpoints or object_id not in endpoints:
                    raise DomainError(f"Identity claim {row['id']} must reference existing entity records.")
                if endpoints[subject].get("kind") != endpoints[object_id].get("kind"):
                    raise DomainError(f"Identity claim {row['id']} endpoints must have the same entity kind.")
            if row.get("predicate") in CAPABILITY_PREDICATES:
                validate_capability_endpoints(row, entity_kinds(records["entities"], records["decisions"]))
            if row.get("predicate") in {"uses", "publishes_to", "calls", "depends_on", "stores_in", "communicates_with", "implements"}:
                if row.get("subject") not in known_entity_ids or row.get("object") not in known_entity_ids:
                    raise DomainError(f"Structural claim {row['id']} references an unknown entity.")
        option_map = {d["id"]: {o["id"] for o in d.get("options", [])} for d in records["decisions"]}
        for row in records["decisions"]:
            for evidence_id in row.get("evidence", []):
                if evidence_id not in ids["evidence"]:
                    raise DomainError(f"Decision {row['id']} references missing evidence {evidence_id}.")
            for option in row.get("options", []):
                missing = set(option.get("evidence", [])) - ids["evidence"]
                if missing:
                    raise DomainError(f"Option {option['id']} references missing evidence: {', '.join(sorted(missing))}.")
                for operation in option.get("delta", {}).get("operations", []):
                    rel = operation.get("relationship", {})
                    if operation["op"] in {"add_relationship", "replace_relationship"}:
                        known = known_entity_ids
                        if rel.get("from") not in known or rel.get("to") not in known:
                            raise DomainError(f"Relationship operation in option {option['id']} references an unknown entity.")
        for row in records["scenarios"]:
            for decision_id, option_id in row.get("selections", {}).items():
                if decision_id not in option_map or option_id not in option_map[decision_id]:
                    raise DomainError(f"Scenario {row['id']} references invalid selection {decision_id}={option_id}.")

    def validate_candidate(self, kind: str, record: dict[str, Any]) -> None:
        """Validate a proposed portable record before writing it to disk."""
        expected = {"entities": "entity", "evidence": "evidence", "aliases": "alias", "claims": "claim", "relationships": "relationship", "decisions": "decision", "scenarios": "scenario", "connections": "model_connection", "agents": "agent_connection"}.get(kind, kind)
        validate_record(record, expected)
        validate_extraction_review(record)
        validate_review_metadata(record)
        schema = __import__("json").loads((self.overlay / "schema" / "record-v1.schema.json").read_text(encoding="utf-8"))
        errors = sorted(Draft202012Validator(schema).iter_errors(record), key=lambda e: list(e.path))
        if errors:
            raise DomainError(errors[0].message)
        self.validate_references((kind, record))

    def validate_identity_endpoints(self, claim: dict[str, Any]) -> None:
        """Validate the local entity endpoints required by a new identity claim."""
        if claim.get("predicate") != "same_entity_as":
            return
        subject, object_id = claim.get("subject"), claim.get("object")
        if subject == object_id:
            raise DomainError(f"Identity claim {claim['id']} must link two distinct entities.")
        endpoints = {entity["id"]: entity for entity in self.records_unchecked("entities")}
        if subject not in endpoints or object_id not in endpoints:
            raise DomainError(f"Identity claim {claim['id']} must reference existing entity records.")
        if endpoints[subject].get("kind") != endpoints[object_id].get("kind"):
            raise DomainError(f"Identity claim {claim['id']} endpoints must have the same entity kind.")

    def records_unchecked(self, kind: str) -> list[dict[str, Any]]:
        directory = self.overlay / kind
        if not directory.exists():
            return []
        schema = __import__("json").loads((self.overlay / "schema" / "record-v1.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        result = []
        for path in sorted(directory.glob("*.yaml")):
            record = load_yaml(path)
            errors = sorted(validator.iter_errors(record), key=lambda e: list(e.path))
            if errors:
                raise DomainError(f"{path}: {errors[0].message}")
            validate_extraction_review(record)
            validate_review_metadata(record)
            result.append(record)
        return result

    def save(self, kind: str, record: dict[str, Any]) -> Path:
        expected = {"entities": "entity", "evidence": "evidence", "aliases": "alias", "claims": "claim", "relationships": "relationship", "decisions": "decision", "scenarios": "scenario", "connections": "model_connection", "agents": "agent_connection"}.get(kind, kind)
        validate_record(record, expected)
        validate_extraction_review(record)
        validate_review_metadata(record)
        schema_path = self.overlay / "schema" / "record-v1.schema.json"
        schema = __import__("json").loads(schema_path.read_text(encoding="utf-8"))
        errors = sorted(Draft202012Validator(schema).iter_errors(record), key=lambda e: list(e.path))
        if errors:
            raise DomainError(errors[0].message)
        if kind == "claims":
            self.validate_identity_endpoints(record)
            if record.get("predicate") in CAPABILITY_PREDICATES:
                validate_capability_endpoints(record, entity_kinds(self.records_unchecked("entities"), self.records_unchecked("decisions")))
        directory = self.overlay / kind
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{record['id']}.yaml"
        serialized = yaml.safe_dump(record, sort_keys=False, allow_unicode=True)
        existing_mode = None
        try:
            existing_mode = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError:
            pass

        temporary_path = None
        descriptor = None
        try:
            while descriptor is None:
                temporary_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
                try:
                    # Use the normal creation mode so the process umask applies to new records.
                    descriptor = os.open(temporary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
                except FileExistsError:
                    continue
            if existing_mode is not None:
                os.fchmod(descriptor, existing_mode)
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
                descriptor = None
                temporary_file.write(serialized)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return path

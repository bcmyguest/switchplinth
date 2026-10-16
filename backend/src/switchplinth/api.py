"""FastAPI surface for the local Switchplinth service."""

from __future__ import annotations

import os
import hashlib
import re
import errno
import stat
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from switchplinth import DEFAULT_CACHE_ROOT, PRODUCT_NAME
from switchplinth.domain import DomainError
from switchplinth.providers import diagnose
from switchplinth.repository import DEFAULT_IGNORES, discover_markdown
from switchplinth.service import DecisionService, ReviewConflictError

REPOSITORY_ROOT = Path(os.environ.get("DECISION_REPO", "/workspace/repository"))
WORKSPACE_ROOT = Path(os.environ.get("DECISION_WORKSPACE_ROOT", str(REPOSITORY_ROOT.parent)))
# Display name for the repository mounted at the workspace root; the mount point name (for example "repos") is not the host name.
WORKSPACE_NAME = os.environ.get("DECISION_WORKSPACE_NAME", "").strip()
ORIGIN_REMOTE_SECTION = re.compile(r'\[remote\s+"origin"\]', re.IGNORECASE)


class ScenarioRequest(BaseModel):
    selections: dict[str, str] = Field(default_factory=dict)


class ScenarioDiffRequest(BaseModel):
    before_selections: dict[str, str] = Field(default_factory=dict)
    after_selections: dict[str, str] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    query: str
    selections: dict[str, str] = Field(default_factory=dict)


class ConnectionRequest(BaseModel):
    id: str
    name: str = ""
    provider: str
    endpoint: str = ""
    model: str = ""
    embedding_model: str | None = None
    credential_ref: str | None = None
    capabilities: dict[str, bool] = Field(default_factory=dict)
    generation: dict[str, Any] | None = None


class ReviewRequest(BaseModel):
    epistemic_state: str


class ExactIdentityReviewRequest(BaseModel):
    entity_ids: list[str]
    epistemic_state: str


class ClaimCorrectionRequest(BaseModel):
    subject: str
    predicate: str
    object: str


class AliasCorrectionRequest(BaseModel):
    name: str
    entity_id: str


class DeltaRequest(BaseModel):
    delta: dict[str, Any]


class DeltaPreviewRequest(BaseModel):
    decision_id: str
    option_id: str
    delta: dict[str, Any]
    selections: dict[str, str] = Field(default_factory=dict)


class ExtractionRequest(BaseModel):
    connection_id: str


class ProposalRequest(BaseModel):
    decision_id: str
    option_id: str
    request: str
    connection_id: str | None = None


class ScenarioSaveRequest(BaseModel):
    name: str
    selections: dict[str, str]
    expected_project_root: str | None = None


class ProjectOpenRequest(BaseModel):
    path: str


def _read_repository_markdown(root: Path, requested_path: str) -> str:
    """Read one Markdown document beneath a repository without following symlinks."""
    if (
        not requested_path
        or "\\" in requested_path
        or Path(requested_path).is_absolute()
        or PureWindowsPath(requested_path).is_absolute()
        or PureWindowsPath(requested_path).drive
        or not requested_path.endswith(".md")
    ):
        raise HTTPException(status_code=422, detail="Source path must be a repository-relative Markdown path.")

    parts = requested_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise HTTPException(status_code=422, detail="Source path must be a safe repository-relative path.")

    resolved_root = root.resolve()
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_fd = -1
    file_fd = -1
    try:
        directory_fd = os.open(resolved_root, directory_flags)
        for part in parts[:-1]:
            next_fd = os.open(part, directory_flags | nofollow, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            parts[-1],
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0) | nofollow,
            dir_fd=directory_fd,
        )
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise HTTPException(status_code=422, detail="Source path must identify a regular Markdown file.")
        with os.fdopen(file_fd, "rb") as source_file:
            file_fd = -1
            return source_file.read().decode("utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Source document not found.") from exc
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise HTTPException(status_code=422, detail="Source path may not traverse symlinks or non-directories.") from exc
        raise HTTPException(status_code=404, detail="Source document not found.") from exc
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="Source document is not valid UTF-8 Markdown.") from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def _origin_repository_name(root: Path) -> str:
    """Return the last path segment of the origin remote URL in `<root>/.git/config`, without `.git`, or "" when absent."""
    try:
        lines = (root / ".git" / "config").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    in_origin = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_origin = ORIGIN_REMOTE_SECTION.fullmatch(stripped) is not None
        elif in_origin:
            key, separator, value = stripped.partition("=")
            if separator and key.strip().lower() == "url":
                return re.split(r"[/:\\]", value.strip().rstrip("/"))[-1].removesuffix(".git")
    return ""


def _repository_name(app: FastAPI, path: Path) -> str:
    """Name a repository for display.

    The mounted workspace root uses DECISION_WORKSPACE_NAME, then the origin remote's repository name, then its
    directory name; the mount point name (for example "repos") is rarely the host name.
    """
    if path.resolve() == app.state.workspace_root:
        return app.state.workspace_name or _origin_repository_name(path) or path.name
    return path.name


def create_app(service: DecisionService | None = None) -> FastAPI:
    app = FastAPI(title=f"{PRODUCT_NAME} API", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type", "Accept"])
    app.state.workspace_root = WORKSPACE_ROOT.resolve()
    app.state.workspace_name = WORKSPACE_NAME
    app.state.service = service or DecisionService(REPOSITORY_ROOT)
    app.state.cache_root = Path(os.environ.get("DECISION_CACHE", DEFAULT_CACHE_ROOT))

    from switchplinth.mcp_tools import create_mcp_server
    mcp_server = create_mcp_server(lambda: app.state.service)
    app.state.mcp_server = mcp_server
    mcp_app = mcp_server.streamable_http_app()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/project")
    def project() -> dict[str, Any]:
        return {"name": _repository_name(app, app.state.service.root), "root": str(app.state.service.root), "format_version": "decision/v1"}

    @app.get("/api/v1/source")
    def source_document(path: str) -> dict[str, str]:
        content = _read_repository_markdown(app.state.service.root, path)
        return {"path": path, "content": content}

    @app.get("/api/v1/repositories")
    def repositories() -> dict[str, Any]:
        root = app.state.workspace_root
        candidates = [root] if root.is_dir() else []
        if root.is_dir():
            candidates.extend(path for path in root.iterdir() if path.is_dir() and not path.is_symlink() and not path.name.startswith(".") and path.name not in DEFAULT_IGNORES)
        valid = [path for path in candidates if (path / ".git").exists() or (path / ".decision").exists() or bool(discover_markdown(path))]
        return {"workspace": str(root), "repositories": [{"path": path.relative_to(root).as_posix() or ".", "name": _repository_name(app, path)} for path in valid]}

    @app.post("/api/v1/project/open")
    def open_project(request: ProjectOpenRequest) -> dict[str, Any]:
        relative = Path(request.path)
        if relative.is_absolute() or "\\" in request.path or any(part in {"..", ""} for part in request.path.split("/")) and request.path != ".":
            raise HTTPException(status_code=422, detail="Repository path must be a safe relative path under the configured workspace.")
        root = app.state.workspace_root
        candidate = root / relative
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise HTTPException(status_code=404, detail="Repository directory does not exist.") from exc
        if root not in resolved.parents and resolved != root or not resolved.is_dir():
            raise HTTPException(status_code=422, detail="Repository path escapes the configured workspace or is not a directory.")
        # Reject symlink traversal even when its target remains within the root.
        cursor = root
        for part in relative.parts if request.path != "." else ():
            cursor = cursor / part
            if cursor.is_symlink():
                raise HTTPException(status_code=422, detail="Repository paths may not traverse symlinks.")
        if not ((resolved / ".git").exists() or (resolved / ".decision").exists() or discover_markdown(resolved)):
            raise HTTPException(status_code=422, detail="Directory is not a repository candidate: no Markdown, .git, or .decision marker found.")
        namespace = hashlib.sha256(resolved.as_posix().encode()).hexdigest()[:16]
        app.state.service = DecisionService(resolved, app.state.cache_root / namespace)
        return {"project": {"name": _repository_name(app, resolved), "root": str(resolved), "format_version": "decision/v1"}}

    @app.post("/api/v1/discovery/scan")
    def scan() -> dict[str, Any]:
        try:
            return app.state.service.scan()
        except (OSError, DomainError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/extraction/run")
    def extraction(request: ExtractionRequest) -> dict[str, Any]:
        try:
            return app.state.service.extract_with_provider(request.connection_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown model connection {request.connection_id}") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Provider extraction failed: {type(exc).__name__}: {exc}") from exc

    @app.get("/api/v1/graph")
    def graph() -> dict[str, Any]:
        try:
            return app.state.service.graph_json()
        except (OSError, DomainError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/decisions")
    def decisions() -> list[dict[str, Any]]:
        return app.state.service.graph_json(annotate=False)["decisions"]

    @app.patch("/api/v1/decisions/{decision_id}/options/{option_id}")
    def edit_option(decision_id: str, option_id: str, request: DeltaRequest) -> dict[str, Any]:
        records = app.state.service.repository.records("decisions")
        record = next((item for item in records if item["id"] == decision_id), None)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Unknown decision {decision_id}")
        option = next((item for item in record.get("options", []) if item["id"] == option_id), None)
        if option is None:
            raise HTTPException(status_code=404, detail=f"Unknown option {option_id}")
        option["delta"] = request.delta
        record["epistemic_state"] = "asserted"
        record["human_modified"] = True
        extraction_review = record.get("extraction_review")
        if extraction_review:
            remaining = [item for item in extraction_review.get("rejected_options", []) if item.get("option_id") != option_id]
            if remaining:
                record["extraction_review"] = {**extraction_review, "rejected_options": remaining}
            else:
                record.pop("extraction_review", None)
        try:
            app.state.service.repository.validate_candidate("decisions", record)
            app.state.service.repository.save("decisions", record)
        except DomainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"decision_id": decision_id, "option_id": option_id, "delta": option["delta"], "extraction_review": record.get("extraction_review")}

    @app.post("/api/v1/scenarios/resolve")
    def resolve(request: ScenarioRequest) -> dict[str, Any]:
        graph = app.state.service.graph_json(request.selections)
        return {"graph": graph, "affected": graph["scenario"]["affected"], "conflicts": graph["scenario"]["conflicts"], "invalid_assumptions": graph["scenario"]["invalid_assumptions"], "unmet_requirements": graph["scenario"]["unmet_requirements"], "impact": graph["scenario"]["impact"], "receipt": graph["receipt"]}

    @app.post("/api/v1/scenarios/diff")
    def diff_scenarios(request: ScenarioDiffRequest) -> dict[str, Any]:
        return app.state.service.diff_scenarios(request.before_selections, request.after_selections)

    @app.post("/api/v1/scenarios/preview-delta")
    def preview_delta(request: DeltaPreviewRequest) -> dict[str, Any]:
        try:
            return app.state.service.preview_delta(request.decision_id, request.option_id, request.delta, request.selections)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown decision or option: {exc}") from exc
        except DomainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/scenarios")
    def save_scenario(request: ScenarioSaveRequest) -> dict[str, Any]:
        service = app.state.service
        if request.expected_project_root is not None and request.expected_project_root != str(service.root):
            raise HTTPException(status_code=409, detail="The active repository changed before this scenario could be saved.")
        try:
            return service.save_scenario(request.name, request.selections)
        except DomainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/scenarios")
    def list_scenarios() -> list[dict[str, Any]]:
        try:
            return app.state.service.list_scenarios()
        except DomainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/scenarios/propose")
    def propose_scenario(request: ProposalRequest) -> dict[str, Any]:
        try:
            return app.state.service.propose_delta(request.decision_id, request.option_id, request.request, request.connection_id)
        except LookupError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown decision or option: {exc}") from exc
        except DomainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Provider proposal failed: {type(exc).__name__}: {exc}") from exc

    @app.get("/api/v1/entities/{entity_id}")
    def entity(entity_id: str, selections: str | None = None) -> dict[str, Any]:
        try:
            parsed_selections = None
            if selections:
                import json
                parsed_selections = json.loads(selections)
                if not isinstance(parsed_selections, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in parsed_selections.items()):
                    raise ValueError("selections must be a JSON object of decision IDs to option IDs")
            return app.state.service.entity_detail(entity_id, parsed_selections)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid selections query: {exc}") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown entity {entity_id}") from exc

    @app.post("/api/v1/search")
    def search(request: SearchRequest) -> dict[str, Any]:
        return app.state.service.search(request.query, request.selections)

    @app.get("/api/v1/connections")
    def connections() -> list[dict[str, Any]]:
        return [{k: v for k, v in item.items() if k != "credential_ref"} for item in app.state.service.connections.values()]

    @app.post("/api/v1/connections")
    def save_connection(request: ConnectionRequest) -> dict[str, Any]:
        try:
            return app.state.service.configure_connection(request.model_dump(exclude_none=True))
        except DomainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/connections/{connection_id}/test")
    def test_connection(connection_id: str) -> dict[str, Any]:
        item = app.state.service.connections.get(connection_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"Unknown connection {connection_id}")
        return diagnose(item)

    @app.post("/api/v1/claims/{claim_id}/review")
    def review_claim(claim_id: str, request: ReviewRequest) -> dict[str, Any]:
        decision = request.epistemic_state
        if decision not in {"confirmed", "rejected", "asserted"}:
            raise HTTPException(status_code=422, detail="decision must be confirmed, rejected, or asserted")
        try:
            return app.state.service.review_claim(claim_id, decision)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown claim {claim_id}") from exc
        except DomainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/identity-candidates/review")
    def review_exact_identity_candidate(request: ExactIdentityReviewRequest) -> dict[str, Any]:
        if request.epistemic_state not in {"confirmed", "asserted", "rejected"}:
            raise HTTPException(status_code=422, detail="epistemic_state must be confirmed, asserted, or rejected")
        try:
            return app.state.service.review_exact_identity_candidate(request.entity_ids, request.epistemic_state)
        except DomainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/aliases/{alias_id}/review")
    def review_alias(alias_id: str, request: ReviewRequest) -> dict[str, Any]:
        decision = request.epistemic_state
        if decision not in {"confirmed", "rejected", "asserted"}:
            raise HTTPException(status_code=422, detail="decision must be confirmed, rejected, or asserted")
        try:
            return app.state.service.review_alias(alias_id, decision)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown alias {alias_id}") from exc

    @app.post("/api/v1/claims/{claim_id}/correct")
    def correct_claim(claim_id: str, request: ClaimCorrectionRequest) -> dict[str, Any]:
        try:
            return app.state.service.correct_claim(claim_id, request.subject, request.predicate, request.object)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown claim {claim_id}") from exc
        except DomainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/aliases/{alias_id}/correct")
    def correct_alias(alias_id: str, request: AliasCorrectionRequest) -> dict[str, Any]:
        try:
            return app.state.service.correct_alias(alias_id, request.name, request.entity_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown alias {alias_id}") from exc
        except DomainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/reviews")
    def review_log() -> dict[str, Any]:
        try:
            return app.state.service.review_log()
        except DomainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/reviews/{record_id}/undo")
    def undo_review(record_id: str) -> dict[str, Any]:
        try:
            return app.state.service.undo_review(record_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown review record {record_id}") from exc
        except ReviewConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except DomainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/providers/status")
    def provider_status() -> dict[str, Any]:
        return {"connections": connections(), "diagnostics_available": True}

    # FastAPI does not run a mounted Starlette child's lifespan. Enter the MCP
    # session manager from the parent lifespan and mount at root so the MCP
    # app's own /mcp route remains the public /mcp endpoint.
    app.router.lifespan_context = lambda _application: mcp_server.session_manager.run()
    app.mount("/", mcp_app)
    return app


app = create_app()


def run() -> None:
    import uvicorn
    uvicorn.run("switchplinth.api:app", host="0.0.0.0", port=8000)

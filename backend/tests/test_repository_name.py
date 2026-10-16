from pathlib import Path

from fastapi.testclient import TestClient

from switchplinth.api import create_app
from switchplinth.service import DecisionService


def _write_markdown_repository(root: Path) -> None:
    (root / "docs").mkdir(parents=True)
    (root / "docs/notes.md").write_text("# Notes\n\nThe API publishes events.\n", encoding="utf-8")


def test_workspace_root_uses_configured_display_name(tmp_path: Path) -> None:
    workspace = tmp_path / "repos"
    _write_markdown_repository(workspace)
    (workspace / "child").mkdir()
    _write_markdown_repository(workspace / "child")
    app = create_app(DecisionService(workspace, tmp_path / "cache"))
    app.state.workspace_root = workspace.resolve()
    app.state.workspace_name = "food-delivery"
    client = TestClient(app)

    assert client.get("/api/v1/project").json()["name"] == "food-delivery"
    names = {item["path"]: item["name"] for item in client.get("/api/v1/repositories").json()["repositories"]}
    assert names["."] == "food-delivery"
    assert names["child"] == "child"


def test_workspace_root_falls_back_to_directory_name(tmp_path: Path) -> None:
    workspace = tmp_path / "repos"
    _write_markdown_repository(workspace)
    app = create_app(DecisionService(workspace, tmp_path / "cache"))
    app.state.workspace_root = workspace.resolve()
    app.state.workspace_name = ""

    assert TestClient(app).get("/api/v1/project").json()["name"] == "repos"

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from switchplinth.api import create_app
from switchplinth.service import DecisionService


def _write_markdown_repository(root: Path) -> None:
    (root / "docs").mkdir(parents=True)
    (root / "docs/notes.md").write_text("# Notes\n\nThe API publishes events.\n", encoding="utf-8")


def _workspace_app(workspace: Path, cache: Path, name: str = ""):
    app = create_app(DecisionService(workspace, cache))
    app.state.workspace_root = workspace.resolve()
    app.state.workspace_name = name
    return TestClient(app)


def _write_git_config(root: Path, text: str) -> None:
    (root / ".git").mkdir()
    (root / ".git/config").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("url", [
    "git@github.com:bcmyguest/switchplinth.git",
    "https://github.com/bcmyguest/switchplinth.git",
    "https://github.com/bcmyguest/switchplinth/",
    "ssh://git@example.com/team/switchplinth",
])
def test_workspace_root_uses_origin_repository_name(tmp_path: Path, url: str) -> None:
    workspace = tmp_path / "repos"
    _write_markdown_repository(workspace)
    _write_git_config(workspace, f'[core]\n\tbare = false\n[remote "upstream"]\n\turl = https://example.com/other.git\n[remote "origin"]\n\turl = {url}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n')
    client = _workspace_app(workspace, tmp_path / "cache")

    assert client.get("/api/v1/project").json()["name"] == "switchplinth"
    names = {item["path"]: item["name"] for item in client.get("/api/v1/repositories").json()["repositories"]}
    assert names["."] == "switchplinth"


def test_configured_name_takes_precedence_over_origin(tmp_path: Path) -> None:
    workspace = tmp_path / "repos"
    _write_markdown_repository(workspace)
    _write_git_config(workspace, '[remote "origin"]\n\turl = git@github.com:bcmyguest/switchplinth.git\n')

    assert _workspace_app(workspace, tmp_path / "cache", "food-delivery").get("/api/v1/project").json()["name"] == "food-delivery"


def test_workspace_root_without_origin_uses_directory_name(tmp_path: Path) -> None:
    workspace = tmp_path / "repos"
    _write_markdown_repository(workspace)
    _write_git_config(workspace, '[remote "upstream"]\n\turl = https://example.com/other.git\n')

    assert _workspace_app(workspace, tmp_path / "cache").get("/api/v1/project").json()["name"] == "repos"


def test_child_repository_ignores_its_origin(tmp_path: Path) -> None:
    workspace = tmp_path / "repos"
    _write_markdown_repository(workspace)
    child = workspace / "child"
    _write_markdown_repository(child)
    _write_git_config(child, '[remote "origin"]\n\turl = https://example.com/renamed.git\n')

    names = {item["path"]: item["name"] for item in _workspace_app(workspace, tmp_path / "cache").get("/api/v1/repositories").json()["repositories"]}
    assert names["child"] == "child"

"""End-to-end wizard runs on the food-delivery sample in a temporary HOME, plus the Docker runtime adapter."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from switchplinth.setup.prompts import ConsolePrompter, SetupError
from switchplinth.setup.runtime import DockerRuntime, compose_env, render_env_file
from switchplinth.setup.verify import verify_stdio
from switchplinth.setup.wizard import WizardContext, run_setup

EXPECTED_TOOLS = ("diff_scenarios", "inspect_architecture", "inspect_entity", "list_decisions", "search_decisions")
OFFLINE_ENV = {"QDRANT_URL": "http://127.0.0.1:9", "NO_PROXY": "*"}


def only_python(name: str) -> str | None:
    """No `switchplinth` script or `claude` CLI: the wizard falls back to `python -m switchplinth.cli`."""
    return None


@pytest.fixture
def home(tmp_path: Path) -> dict[str, str]:
    """The wizard reads DECISION_CACHE from this env, not os.environ; no caller variable may redirect the sample."""
    env = {key: value for key, value in os.environ.items() if not key.startswith(("XDG_", "CLAUDE")) and key != "DECISION_DEMO_WORKSPACE"}
    return {**env, **OFFLINE_ENV, "HOME": str(tmp_path / "home"), "DECISION_CACHE": str(tmp_path / "cache")}


def run(argv: list[str], env: dict[str, str], prompter=None, platform: str = "linux", which=only_python) -> tuple[int, str]:
    lines: list[str] = []
    code = run_setup(argv, WizardContext(env=env, out=lines.append, prompter=prompter, platform=platform, which=which))
    return code, "\n".join(lines)


def test_unattended_local_run_on_sample_is_idempotent(home: dict[str, str]) -> None:
    argv = ["--sample", "--mode", "local", "--client", "claude-desktop", "--yes"]
    code, output = run(argv, home)
    assert code == 0, output
    sample = Path(home["HOME"]) / ".cache" / "switchplinth-demo" / "food-delivery"
    assert "Bootstrapped the food-delivery sample" in output
    assert "7 decisions" in output
    assert "tools/list: " + ", ".join(EXPECTED_TOOLS) in output
    config = Path(home["HOME"]) / ".config" / "Claude" / "claude_desktop_config.json"
    entry = json.loads(config.read_text())["mcpServers"]["switchplinth"]
    assert entry == {"command": sys.executable, "args": ["-m", "switchplinth.cli", "mcp", "--repo", str(sample)]}
    snapshot = config.read_text()

    code, output = run(argv, home)
    assert code == 0, output
    assert "Reusing the food-delivery sample" in output
    assert "already has this server; nothing to change" in output
    assert config.read_text() == snapshot
    assert sorted(path.name for path in config.parent.iterdir()) == ["claude_desktop_config.json"]


def test_interactive_run_declined_write_leaves_config(home: dict[str, str], tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "notes.md").write_text("# Messaging\n\nWe decided to adopt Kafka for order events.\n")
    cursor = Path(home["HOME"]) / ".cursor" / "mcp.json"
    cursor.parent.mkdir(parents=True)
    original = '{"mcpServers": {"other": {"command": "other"}}}\n'
    cursor.write_text(original)
    # repo, mode, provider, client, Proceed?, write config?
    answers = iter([str(repo), "local", "none", "cursor", "y", "n"])
    out = io.StringIO()
    code, output = run(["--no-verify"], home, ConsolePrompter(lambda: next(answers) + "\n", out))
    assert code == 2
    assert "Setup stopped: Left" in output
    assert cursor.read_text() == original
    assert sorted(path.name for path in cursor.parent.iterdir()) == ["mcp.json"]
    assert f"Write this change to {cursor}?" in out.getvalue()


def test_print_client_shows_every_snippet_and_writes_nothing(home: dict[str, str], tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Service\n\nThe order service publishes events to Kafka.\n")
    code, output = run(["--repo", str(repo), "--mode", "local", "--client", "print", "--no-verify", "--yes"], home)
    assert code == 0, output
    for marker in ("claude mcp add --scope user switchplinth --", '"mcpServers"', '"servers"', '"type": "stdio"'):
        assert marker in output
    assert not Path(home["HOME"]).exists()


def test_malformed_client_config_stops_with_clear_error(home: dict[str, str], tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Service\n\nThe order service publishes events to Kafka.\n")
    config = Path(home["HOME"]) / ".config" / "Code" / "User" / "mcp.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"servers": {,}}')
    code, output = run(["--repo", str(repo), "--mode", "local", "--client", "vscode", "--no-verify", "--yes"], home)
    assert code == 2
    assert "is not valid JSON" in output and "nothing was written" in output
    assert config.read_text() == '{"servers": {,}}'


def test_verify_stdio_against_real_server_on_fixture(home: dict[str, str]) -> None:
    code, output = run(["--sample", "--mode", "local", "--client", "print", "--no-verify", "--yes"], home)
    assert code == 0, output
    sample = Path(home["HOME"]) / ".cache" / "switchplinth-demo" / "food-delivery"
    result = verify_stdio([sys.executable, "-m", "switchplinth.cli", "mcp", "--repo", str(sample)], home)
    assert result.server_name == "io.github.bcmyguest/switchplinth"
    assert result.tools == EXPECTED_TOOLS


def test_verify_stdio_reports_a_broken_command(home: dict[str, str], tmp_path: Path) -> None:
    with pytest.raises(Exception, match="Repository directory not found"):
        verify_stdio([sys.executable, "-m", "switchplinth.cli", "mcp", "--repo", str(tmp_path / "missing")], home, timeout=30)


class FakeHttp:
    def __init__(self):
        self.requests: list[tuple[str, str]] = []

    def get(self, url, timeout):
        return type("R", (), {"status_code": 200})()

    def request(self, method, url, timeout, **kwargs):
        self.requests.append((method, url))
        return type("R", (), {"status_code": 200, "json": lambda self: {}, "text": ""})()


def docker_runtime(tmp_path: Path, calls: list, ps_output: str = "", free: bool = True, credential: str | None = None, mounted: str | None = None, confirm_replace=None) -> DockerRuntime:
    def fake_run(args, **kwargs):
        calls.append((args, kwargs.get("env")))
        stdout = ""
        if args[-2:] == ["ps", "-q"]:
            stdout = ps_output
        elif args[:3] == ["docker", "ps", "-aq"] and mounted is not None:
            stdout = "backend123\n"
        elif args[:2] == ["docker", "inspect"] and mounted is not None:
            stdout = mounted + "\n"
        return subprocess.CompletedProcess(args, 0, stdout, "")

    return DockerRuntime(tmp_path / "repo", tmp_path / "checkout", tmp_path / "state", "swp-wizard-test", {"frontend": 3390, "backend": 8390, "qdrant": 6390}, credential, {"PATH": "/usr/bin"}, lambda _line: None, fake_run, FakeHttp(), lambda _port: free, confirm_replace)


def test_docker_runtime_writes_env_without_secrets_and_starts_stack(tmp_path: Path) -> None:
    calls: list = []
    runtime = docker_runtime(tmp_path, calls, credential="OPENAI_API_KEY")
    runtime.start()
    env_text = runtime.env_file.read_text()
    assert "DECISION_BACKEND_PORT=8390" in env_text and "COMPOSE_PROJECT_NAME=swp-wizard-test" in env_text
    assert f"DECISION_WORKSPACE_HOST={tmp_path / 'repo'}" in env_text
    assert runtime.override_file.read_text().endswith("      - OPENAI_API_KEY\n")
    up_args, up_env = calls[-1]
    assert up_args[-8:-1] == ["-p", "swp-wizard-test", "up", "-d", "--build", "--wait", "--wait-timeout"]
    override_at = up_args.index(str(runtime.override_file))
    assert up_args[override_at - 1] == "-f"
    assert up_env["DECISION_BACKEND_PORT"] == "8390" and up_env["PATH"] == "/usr/bin"
    assert render_env_file(compose_env(tmp_path / "repo", "swp-wizard-test", runtime.ports)) == env_text


def test_docker_runtime_refuses_busy_ports_for_new_project(tmp_path: Path) -> None:
    calls: list = []
    with pytest.raises(SetupError, match="Loopback ports in use: frontend 3390, backend 8390, qdrant 6390"):
        docker_runtime(tmp_path, calls, free=False).start()
    assert not any("up" in args for args, _env in calls)


def test_docker_runtime_rerun_skips_port_check_when_project_runs(tmp_path: Path) -> None:
    calls: list = []
    docker_runtime(tmp_path, calls, ps_output="abc123\n", free=False).start()
    assert any("up" in args for args, _env in calls)


def _ran_up(calls: list) -> bool:
    return any("up" in args for args, _env in calls)


def test_docker_runtime_refuses_running_project_on_other_workspace(tmp_path: Path) -> None:
    calls: list = []
    with pytest.raises(SetupError, match="already running with workspace /elsewhere.*--replace-workspace"):
        docker_runtime(tmp_path, calls, ps_output="abc\n", mounted="/elsewhere").start()
    assert not _ran_up(calls)
    assert not (tmp_path / "state").exists()
    inspect = next(args for args, _env in calls if args[:2] == ["docker", "inspect"])
    assert '"/workspace/repos"' in inspect[3]


def test_docker_runtime_declined_replace_leaves_project(tmp_path: Path) -> None:
    calls: list = []
    questions: list[str] = []
    with pytest.raises(SetupError, match="left it unchanged"):
        docker_runtime(tmp_path, calls, ps_output="abc\n", mounted="/elsewhere", confirm_replace=lambda q: questions.append(q) or False).start()
    assert questions and "Restart it on" in questions[0]
    assert not _ran_up(calls)


def test_docker_runtime_replaces_running_project_when_confirmed(tmp_path: Path) -> None:
    calls: list = []
    docker_runtime(tmp_path, calls, ps_output="abc\n", mounted="/elsewhere", confirm_replace=lambda _q: True).start()
    assert _ran_up(calls)


def test_docker_runtime_same_workspace_needs_no_confirmation(tmp_path: Path) -> None:
    calls: list = []
    docker_runtime(tmp_path, calls, ps_output="abc\n", mounted=str(tmp_path / "repo"), confirm_replace=lambda _q: pytest.fail("must not ask")).start()
    assert _ran_up(calls)


def _repo_with_markdown(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Service\n\nThe order service publishes events to Kafka.\n")
    return repo


@pytest.mark.parametrize("client", ["claude-code", "cursor", "claude-desktop", "vscode"])
def test_windows_prints_every_client_and_runs_nothing(home: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: str) -> None:
    repo = _repo_with_markdown(tmp_path)
    for writer in ("register_claude_code", "register_file_client"):
        monkeypatch.setattr(f"switchplinth.setup.wizard.{writer}", lambda *a, **k: pytest.fail("must not register"))
    code, output = run(["--repo", str(repo), "--mode", "local", "--client", client, "--no-verify", "--yes"], home, platform="win32", which=lambda name: f"C:/bin/{name}.exe")
    assert code == 0, output
    assert "On Windows setup writes no client config and runs no client CLI" in output
    assert ("claude mcp add --scope user switchplinth --" in output) if client == "claude-code" else ('"command"' in output)
    assert "claude mcp get" not in output
    assert not Path(home["HOME"]).exists()


def test_windows_docker_mode_stops_before_any_change(home: dict[str, str], tmp_path: Path) -> None:
    repo = _repo_with_markdown(tmp_path)
    code, output = run(["--repo", str(repo), "--mode", "docker", "--client", "print", "--yes"], home, platform="win32")
    assert code == 2
    assert "does not drive Docker on Windows" in output
    assert not (repo / ".decision").exists()

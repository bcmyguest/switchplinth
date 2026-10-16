"""Flag parsing, unattended and interactive plans, repository validation, and secret handling."""

from __future__ import annotations

import argparse
import io
from pathlib import Path

import pytest

from switchplinth.service import DecisionService
from switchplinth.setup.connection import ConnectionChoice, connection_record, credential_reference, endpoint_for_docker, list_models
from switchplinth.setup.plan import add_arguments, resolve_plan
from switchplinth.setup.prompts import ConsolePrompter, SetupError, UnattendedPrompter
from switchplinth.setup.workspace import sample_path, validate_repository

SECRET_VALUE = "test-secret-value-not-a-key"


def parse(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    add_arguments(parser)
    return parser.parse_args(list(argv))


def no_switchplinth(name: str) -> str | None:
    return None


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "docs-repo"
    (root / "adr").mkdir(parents=True)
    (root / "adr" / "0001-queue.md").write_text("# Use a queue\n\nWe decided to adopt a queue for order events.\n")
    return root


def resolve(args: argparse.Namespace, prompter, env=None, models=(), which=no_switchplinth, platform="linux"):
    lines: list[str] = []
    plan = resolve_plan(args, prompter, env or {"HOME": "/home/tester"}, lines.append, which=which, list_models=lambda _choice, _env: list(models), platform=platform)
    return plan, lines


def test_unattended_flags_build_full_plan(repo: Path) -> None:
    args = parse("--repo", str(repo), "--mode", "docker", "--provider", "openai-compatible", "--endpoint", "http://localhost:8080/api/v1/", "--model", "qwen", "--reasoning-off", "--client", "cursor", "--backend-port", "8390", "--project", "swp-test", "--yes")
    plan, _ = resolve(args, UnattendedPrompter(), models=["qwen", "nomic"])
    assert plan.repo == repo.resolve() and not plan.sample
    assert plan.mode == "docker" and plan.client == "cursor" and plan.project == "swp-test"
    assert plan.ports == {"frontend": 3000, "backend": 8390, "qdrant": 6333}
    assert plan.connection == ConnectionChoice("openai-compatible", "http://localhost:8080/api/v1", "qwen", None, True)
    assert plan.server_command[-3:] == ("mcp", "--repo", str(repo.resolve()))
    assert plan.server_command[1:3] == ("-m", "switchplinth.cli")


def test_unattended_defaults_choose_sample_local_none_print() -> None:
    plan, _ = resolve(parse("--yes"), UnattendedPrompter(), env={"HOME": "/home/tester"})
    assert plan.sample and plan.repo == Path("/home/tester/.cache/switchplinth-demo/food-delivery")
    assert (plan.mode, plan.connection.provider, plan.client) == ("local", "none", "print")


def test_unattended_requires_model_for_provider(repo: Path) -> None:
    with pytest.raises(SetupError, match="Model: no value given"):
        resolve(parse("--repo", str(repo), "--provider", "openai-compatible", "--yes"), UnattendedPrompter())


def test_interactive_prompts_only_for_missing_answers(repo: Path, tmp_path: Path) -> None:
    # repo (missing), repo, mode, provider, endpoint, API key env (none), model, reasoning off?, client
    answers = iter([str(tmp_path / "missing"), str(repo), "", "openai-compatible", "", "", "", "y", "vscode"])
    out = io.StringIO()
    prompter = ConsolePrompter(lambda: next(answers) + "\n", out)
    plan, lines = resolve(parse(), prompter, models=["gemma", "qwen"])
    assert plan.repo == repo.resolve()
    assert plan.mode == "local"
    assert plan.connection == ConnectionChoice("openai-compatible", "http://localhost:8080/v1", "gemma", None, True)
    assert plan.client == "vscode"
    assert any("Repository not found" in line for line in lines)
    assert "Model (gemma): " in out.getvalue()


def test_console_prompter_rejects_invalid_choice_then_accepts() -> None:
    answers = iter(["kubernetes\n", "docker\n"])
    out = io.StringIO()
    assert ConsolePrompter(lambda: next(answers), out).ask("Mode", "local", ("local", "docker")) == "docker"
    assert "Choose one of: local, docker." in out.getvalue()


def test_console_prompter_reports_end_of_input() -> None:
    with pytest.raises(SetupError, match="Input ended"):
        ConsolePrompter(lambda: "", io.StringIO()).ask("Mode", "local")


def test_flag_with_invalid_repository_fails_even_interactively(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    prompter = ConsolePrompter(lambda: pytest.fail("must not prompt"), io.StringIO())
    with pytest.raises(SetupError, match="No Markdown files"):
        resolve(parse("--repo", str(empty)), prompter)


def test_repository_validation(tmp_path: Path, repo: Path) -> None:
    assert validate_repository(repo) == (repo.resolve(), 1)
    with pytest.raises(SetupError, match="not found"):
        validate_repository(tmp_path / "nope")
    (tmp_path / "file.md").write_text("# x\n")
    with pytest.raises(SetupError, match="not a directory"):
        validate_repository(tmp_path / "file.md")
    only_hidden = tmp_path / "hidden"
    (only_hidden / "node_modules" / "pkg").mkdir(parents=True)
    (only_hidden / "node_modules" / "pkg" / "README.md").write_text("# pkg\n")
    with pytest.raises(SetupError, match="No Markdown files"):
        validate_repository(only_hidden)
    with pytest.raises(SetupError, match="filesystem root"):
        validate_repository(Path("/"))


def test_sample_path_matches_demo_script() -> None:
    assert sample_path({"HOME": "/h"}) == Path("/h/.cache/switchplinth-demo/food-delivery")
    assert sample_path({"HOME": "/h", "XDG_CACHE_HOME": "/c"}) == Path("/c/switchplinth-demo/food-delivery")
    assert sample_path({"HOME": "/h", "DECISION_DEMO_WORKSPACE": "/w"}) == Path("/w/food-delivery")


@pytest.mark.parametrize("value", [SECRET_VALUE, "sk-ant-api03-abc", "my key", "1PASSWORD"])
def test_credential_must_be_an_environment_variable_name(value: str) -> None:
    with pytest.raises(SetupError, match="NAME of an environment variable"):
        credential_reference(value)


def test_credential_reference_is_env_only() -> None:
    assert credential_reference("OPENAI_API_KEY") == "env:OPENAI_API_KEY"
    assert credential_reference("env:ANTHROPIC_API_KEY") == "env:ANTHROPIC_API_KEY"
    assert credential_reference(None) is None


def test_hosted_provider_needs_credential_env() -> None:
    with pytest.raises(SetupError, match="credential environment variable"):
        connection_record(ConnectionChoice("openai", model="gpt-x"))
    record = connection_record(ConnectionChoice("anthropic", model="claude-x", credential_env="ANTHROPIC_API_KEY"))
    assert record == {"id": "anthropic", "name": "anthropic (claude-x)", "provider": "anthropic", "model": "claude-x", "capabilities": {}, "endpoint": "", "credential_ref": "env:ANTHROPIC_API_KEY"}


def test_interactive_secret_answer_is_rejected(repo: Path) -> None:
    answers = iter(["openai", SECRET_VALUE])
    prompter = ConsolePrompter(lambda: next(answers) + "\n", io.StringIO())
    with pytest.raises(SetupError, match="not the key itself"):
        resolve(parse("--repo", str(repo), "--mode", "local", "--client", "print"), prompter)


def test_docker_endpoint_uses_host_gateway() -> None:
    assert endpoint_for_docker("http://localhost:8080/api/v1") == "http://host.docker.internal:8080/api/v1"
    assert endpoint_for_docker("http://127.0.0.1/v1") == "http://host.docker.internal/v1"
    assert endpoint_for_docker("http://gpu-box:8080/v1") == "http://gpu-box:8080/v1"
    record = connection_record(ConnectionChoice("openai-compatible", "http://localhost:8080/v1", "m", None, True), docker=True)
    assert record["endpoint"] == "http://host.docker.internal:8080/v1"
    assert record["generation"] == {"reasoning": "off"}
    assert "credential_ref" not in record


def test_saved_connection_holds_reference_not_secret(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWP_TEST_KEY", SECRET_VALUE)
    service = DecisionService(repo, tmp_path / "cache")
    service.configure_connection(connection_record(ConnectionChoice("openai", model="gpt-x", credential_env="SWP_TEST_KEY")))
    files = list((repo / ".decision").rglob("*"))
    assert any(path.parent.name == "connections" for path in files)
    for path in files:
        if path.is_file():
            assert SECRET_VALUE not in path.read_text(encoding="utf-8")
    saved = next(path for path in files if path.parent.name == "connections").read_text()
    assert "credential_ref: env:SWP_TEST_KEY" in saved


def test_list_models_reads_catalog_and_sends_secret_only_in_header() -> None:
    seen: dict = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "a"}, {"id": "b"}]}

    def get(url, headers, timeout):
        seen.update(url=url, headers=headers)
        return Response()

    choice = ConnectionChoice("openai-compatible", "http://localhost:8080/v1", credential_env="SWP_TEST_KEY")
    assert list_models(choice, {"SWP_TEST_KEY": SECRET_VALUE}, get) == ["a", "b"]
    assert seen == {"url": "http://localhost:8080/v1/models", "headers": {"Authorization": f"Bearer {SECRET_VALUE}"}}

    def unreachable(*_a, **_k):
        raise OSError("refused")

    assert list_models(choice, {}, unreachable) == []


def test_default_project_differs_from_checkout_compose_name(repo: Path) -> None:
    plan, _ = resolve(parse("--repo", str(repo), "--mode", "docker", "--yes"), UnattendedPrompter())
    assert plan.project == "switchplinth-setup"
    assert not plan.replace_workspace
    assert plan.describe()[-1].strip() == "The client runs this local stdio server, not the container's HTTP /mcp."
    with pytest.raises(TypeError):
        plan.ports["backend"] = 1  # type: ignore[index]


def test_interactive_openai_compatible_asks_for_key_env_and_reasoning_with_model_flag(repo: Path) -> None:
    # repo, mode, endpoint, API key env, reasoning off?, client
    answers = iter([str(repo), "", "", "LOCAL_LLM_KEY", "y", "print"])
    out = io.StringIO()
    plan, _ = resolve(parse("--provider", "openai-compatible", "--model", "qwen"), ConsolePrompter(lambda: next(answers) + "\n", out), env={"HOME": "/h", "LOCAL_LLM_KEY": "x"})
    assert plan.connection == ConnectionChoice("openai-compatible", "http://localhost:8080/v1", "qwen", "LOCAL_LLM_KEY", True)
    assert "Name of the environment variable holding the API key, or 'none'" in out.getvalue()
    assert "Turn model reasoning/thinking off" in out.getvalue()


def test_windows_refuses_docker_mode(repo: Path) -> None:
    with pytest.raises(SetupError, match="does not drive Docker on Windows"):
        resolve(parse("--repo", str(repo), "--mode", "docker", "--yes"), UnattendedPrompter(), platform="win32")


def test_windows_defaults_to_print_even_with_claude_on_path(repo: Path) -> None:
    def which(name: str) -> str | None:
        return "C:/bin/claude.exe" if name == "claude" else None

    plan, _ = resolve(parse("--repo", str(repo), "--yes"), UnattendedPrompter(), which=which, platform="win32")
    assert plan.client == "print"
    plan, _ = resolve(parse("--repo", str(repo), "--yes"), UnattendedPrompter(), which=which, platform="linux")
    assert plan.client == "claude-code"

"""MCP client registration: pure JSON merge, guarded writes, config paths, and the claude CLI."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from switchplinth.setup.clients import apply_merge, config_path, merge_server, parse_claude_get, register_claude_code, register_file_client, server_entry, snippet
from switchplinth.setup.prompts import SetupError

COMMAND = ["/opt/switchplinth/bin/switchplinth", "mcp", "--repo", "/work/repo"]
FIXED_NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)


class ScriptedConfirm:
    interactive = True

    def __init__(self, *answers: bool):
        self.answers = list(answers)
        self.questions: list[str] = []

    def ask(self, question, default=None, choices=()):
        raise AssertionError("no questions expected")

    def confirm(self, question, default=True):
        self.questions.append(question)
        return self.answers.pop(0)


def test_merge_adds_server_and_preserves_other_servers_and_keys() -> None:
    current = json.dumps({"theme": "dark", "mcpServers": {"other": {"command": "other-mcp", "args": []}}}, indent=4)
    result = merge_server(current, "cursor", server_entry("cursor", COMMAND))
    merged = json.loads(result.text)
    assert result.status == "added"
    assert merged["theme"] == "dark"
    assert merged["mcpServers"]["other"] == {"command": "other-mcp", "args": []}
    assert merged["mcpServers"]["switchplinth"] == {"command": COMMAND[0], "args": COMMAND[1:]}
    assert "+    \"switchplinth\": {" in result.diff


def test_merge_is_idempotent_and_updates_changed_entry() -> None:
    first = merge_server(None, "claude-desktop", server_entry("claude-desktop", COMMAND))
    again = merge_server(first.text, "claude-desktop", server_entry("claude-desktop", COMMAND))
    assert again.status == "unchanged" and again.text == first.text and again.diff == ""
    changed = merge_server(first.text, "claude-desktop", server_entry("claude-desktop", [*COMMAND[:-1], "/work/other"]))
    assert changed.status == "updated"
    assert json.loads(changed.text)["mcpServers"]["switchplinth"]["args"][-1] == "/work/other"


def test_vscode_uses_servers_key_and_stdio_type() -> None:
    result = merge_server('{"servers": {"keep": {"type": "http", "url": "http://x"}}}', "vscode", server_entry("vscode", COMMAND))
    servers = json.loads(result.text)["servers"]
    assert servers["keep"] == {"type": "http", "url": "http://x"}
    assert servers["switchplinth"]["type"] == "stdio"


@pytest.mark.parametrize("text, message", [
    ("{not json", "not valid JSON"),
    ("// comment\n{}", "not valid JSON"),
    ("[]", "must contain a JSON object"),
    ('{"mcpServers": []}', "must be a JSON object"),
])
def test_merge_rejects_malformed_config_with_clear_error(text: str, message: str) -> None:
    with pytest.raises(SetupError, match=message):
        merge_server(text, "cursor", server_entry("cursor", COMMAND), "mcp.json")


def test_apply_merge_backs_up_and_writes_atomically(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    original = '{"mcpServers": {"other": {"command": "x"}}}\n'
    path.write_text(original)
    path.chmod(0o640)
    lines: list[str] = []
    result = merge_server(original, "cursor", server_entry("cursor", COMMAND), str(path))
    backup = apply_merge(path, result, ScriptedConfirm(True), lines.append, now=lambda: FIXED_NOW)
    assert backup == tmp_path / "mcp.json.20261016T120000000000Z.bak"
    assert backup.read_text() == original
    assert json.loads(path.read_text())["mcpServers"]["other"] == {"command": "x"}
    assert path.stat().st_mode & 0o777 == 0o640
    assert not list(tmp_path.glob(".mcp.json.*.tmp"))
    assert any("switchplinth" in line for line in lines)


def test_apply_merge_never_writes_without_confirmation(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    original = '{"mcpServers": {}}\n'
    path.write_text(original)
    result = merge_server(original, "cursor", server_entry("cursor", COMMAND), str(path))
    with pytest.raises(SetupError, match="unchanged"):
        apply_merge(path, result, ScriptedConfirm(False), lambda _line: None)
    assert path.read_text() == original
    assert sorted(item.name for item in tmp_path.iterdir()) == ["mcp.json"]


def test_unchanged_merge_does_not_ask_or_back_up(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(merge_server(None, "cursor", server_entry("cursor", COMMAND)).text)
    prompter = ScriptedConfirm()
    result = merge_server(path.read_text(), "cursor", server_entry("cursor", COMMAND), str(path))
    assert apply_merge(path, result, prompter, lambda _line: None) is None
    assert prompter.questions == []
    assert sorted(item.name for item in tmp_path.iterdir()) == ["mcp.json"]


def test_register_file_client_twice_is_idempotent(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path)}
    lines: list[str] = []
    assert register_file_client("claude-desktop", COMMAND, "linux", env, ScriptedConfirm(True), lines.append) == "added"
    target = tmp_path / ".config" / "Claude" / "claude_desktop_config.json"
    first = target.read_text()
    assert register_file_client("claude-desktop", COMMAND, "linux", env, ScriptedConfirm(), lines.append) == "unchanged"
    assert target.read_text() == first
    assert sorted(item.name for item in target.parent.iterdir()) == ["claude_desktop_config.json"]


def test_config_paths_per_platform(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path)}
    assert config_path("cursor", "linux", env) == tmp_path / ".cursor" / "mcp.json"
    assert config_path("cursor", "darwin", env) == tmp_path / ".cursor" / "mcp.json"
    assert config_path("claude-desktop", "darwin", env) == tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    assert config_path("claude-desktop", "linux", {**env, "XDG_CONFIG_HOME": str(tmp_path / "xdg")}) == tmp_path / "xdg" / "Claude" / "claude_desktop_config.json"
    assert config_path("vscode", "linux", env) == tmp_path / ".config" / "Code" / "User" / "mcp.json"
    assert config_path("vscode", "darwin", env) == tmp_path / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    for client in ("cursor", "claude-desktop", "vscode"):
        assert config_path(client, "win32", env) is None


def test_windows_file_clients_print_only(tmp_path: Path) -> None:
    lines: list[str] = []
    assert register_file_client("cursor", COMMAND, "win32", {"HOME": str(tmp_path)}, ScriptedConfirm(), lines.append) == "printed"
    assert '"mcpServers"' in "\n".join(lines)
    assert list(tmp_path.iterdir()) == []


def _completed(code: int, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout, "")


def test_claude_code_prints_command_when_cli_absent() -> None:
    lines: list[str] = []
    status = register_claude_code(COMMAND, "user", ScriptedConfirm(), lines.append, which=lambda _name: None, run=lambda *a, **k: pytest.fail("must not run"))
    assert status == "printed"
    assert "claude mcp add --scope user switchplinth -- /opt/switchplinth/bin/switchplinth mcp --repo /work/repo" in "\n".join(lines)


def test_claude_code_add_then_unchanged() -> None:
    calls: list[list[str]] = []
    registered = {"value": False}

    def run(args, **_kwargs):
        calls.append(args[1:])
        if args[1:3] == ["mcp", "get"]:
            return _completed(0, _get_output(COMMAND)) if registered["value"] else _completed(1)
        if args[1:3] == ["mcp", "add"]:
            registered["value"] = True
        return _completed(0)

    which = lambda _name: "/usr/bin/claude"  # noqa: E731
    assert register_claude_code(COMMAND, "user", ScriptedConfirm(True), lambda _l: None, which, run) == "added"
    assert ["mcp", "add", "--scope", "user", "switchplinth", "--", *COMMAND] in calls
    calls.clear()
    assert register_claude_code(COMMAND, "user", ScriptedConfirm(), lambda _l: None, which, run) == "unchanged"
    assert calls == [["mcp", "get", "switchplinth"]]


def test_claude_code_keeps_different_server_without_confirmation() -> None:
    calls: list[list[str]] = []

    def run(args, **_kwargs):
        calls.append(args[1:])
        return _completed(0, "switchplinth:\n  Command: other\n")

    with pytest.raises(SetupError, match="unchanged"):
        register_claude_code(COMMAND, "user", ScriptedConfirm(False), lambda _l: None, lambda _n: "/usr/bin/claude", run)
    assert calls == [["mcp", "get", "switchplinth"]]


def _get_output(command: list[str], scope_label: str = "User config (available in all your projects)") -> str:
    return f"switchplinth:\n  Scope: {scope_label}\n  Status: Connected\n  Type: stdio\n  Command: {command[0]}\n  Args: {' '.join(command[1:])}\n  Environment:\n"


def test_parse_claude_get_reads_scope_command_and_args() -> None:
    entry = parse_claude_get(_get_output(COMMAND, "Local config (private to you in this project)"))
    assert (entry.scope, entry.command, entry.args) == ("local", COMMAND[0], "mcp --repo /work/repo")


def test_claude_code_repo_prefix_is_not_unchanged() -> None:
    """A registered /work/repo-old must not count as /work/repo just because the text contains it."""
    calls: list[list[str]] = []
    registered = [*COMMAND[:-1], "/work/repo-old"]

    def run(args, **_kwargs):
        calls.append(args[1:])
        return _completed(0, _get_output(registered)) if args[1:3] == ["mcp", "get"] else _completed(0)

    assert register_claude_code(COMMAND, "user", ScriptedConfirm(True), lambda _l: None, lambda _n: "/usr/bin/claude", run) == "updated"
    assert ["mcp", "remove", "--scope", "user", "switchplinth"] in calls
    assert calls[-1] == ["mcp", "add", "--scope", "user", "switchplinth", "--", *COMMAND]


def test_claude_code_removes_from_the_scope_it_found() -> None:
    calls: list[list[str]] = []

    def run(args, **_kwargs):
        calls.append(args[1:])
        return _completed(0, _get_output(COMMAND, "Local config (private to you in this project)")) if args[1:3] == ["mcp", "get"] else _completed(0)

    lines: list[str] = []
    assert register_claude_code(COMMAND, "user", ScriptedConfirm(True), lines.append, lambda _n: "/usr/bin/claude", run) == "updated"
    assert calls[1] == ["mcp", "remove", "--scope", "local", "switchplinth"]
    assert calls[2][:4] == ["mcp", "add", "--scope", "user"]
    assert "takes no backup" in "\n".join(lines)


def test_claude_snippet_uses_requested_scope() -> None:
    assert snippet("claude-code", COMMAND, "project").startswith("claude mcp add --scope project switchplinth --")

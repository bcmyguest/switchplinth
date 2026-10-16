"""MCP client registration: config locations, pure JSON merge, and guarded writes.

`merge_server` is pure: it takes the current file text and returns the new
text, a status, and a unified diff. `apply_merge` is the only writer; it backs
up the original, writes atomically, and never writes without confirmation.
"""

from __future__ import annotations

import difflib
import json
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from switchplinth.setup.prompts import Prompter, SetupError

SERVER_NAME = "switchplinth"
CLIENTS = ("claude-code", "claude-desktop", "cursor", "vscode", "print")
FILE_CLIENTS = ("claude-desktop", "cursor", "vscode")
# Top-level key holding servers in each client's JSON file.
SERVERS_KEY = {"claude-desktop": "mcpServers", "cursor": "mcpServers", "vscode": "servers"}
CLIENT_LABEL = {"claude-code": "Claude Code", "claude-desktop": "Claude Desktop", "cursor": "Cursor", "vscode": "VS Code"}
CLAUDE_SCOPES = ("user", "local", "project")
NO_BACKUP_NOTE = "Claude Code's own CLI writes its config, so setup takes no backup."


@dataclass(frozen=True)
class MergeResult:
    status: str  # "added", "updated", or "unchanged"
    text: str
    diff: str


def config_path(client: str, platform: str, env: Mapping[str, str]) -> Path | None:
    """Return the user-level JSON config for a file client; None where only snippets are supported (Windows)."""
    home = Path(env.get("HOME") or Path.home())
    xdg_config = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
    app_support = home / "Library" / "Application Support"
    match (client, platform):
        case ("cursor", "linux" | "darwin"):
            return home / ".cursor" / "mcp.json"
        case ("claude-desktop", "darwin"):
            return app_support / "Claude" / "claude_desktop_config.json"
        case ("claude-desktop", "linux"):
            return xdg_config / "Claude" / "claude_desktop_config.json"
        case ("vscode", "darwin"):
            return app_support / "Code" / "User" / "mcp.json"
        case ("vscode", "linux"):
            return xdg_config / "Code" / "User" / "mcp.json"
        case _:
            return None


def server_entry(client: str, command: list[str]) -> dict[str, Any]:
    entry: dict[str, Any] = {"command": command[0], "args": command[1:]}
    if client == "vscode":
        return {"type": "stdio", **entry}
    return entry


def snippet(client: str, command: list[str], claude_scope: str = "user") -> str:
    if client == "claude-code":
        return shlex.join(claude_add_command(command, claude_scope))
    return json.dumps({SERVERS_KEY[client]: {SERVER_NAME: server_entry(client, command)}}, indent=2)


def merge_server(current: str | None, client: str, entry: dict[str, Any], label: str = "config") -> MergeResult:
    """Insert or replace one server entry, preserving every other key and server."""
    key = SERVERS_KEY[client]
    if current is None or not current.strip():
        document: dict[str, Any] = {}
    else:
        try:
            document = json.loads(current)
        except json.JSONDecodeError as exc:
            raise SetupError(f"{label} is not valid JSON (line {exc.lineno}, column {exc.colno}: {exc.msg}). Fix or move it, then rerun; nothing was written.") from exc
        if not isinstance(document, dict):
            raise SetupError(f"{label} must contain a JSON object; nothing was written.")
    servers = document.get(key, {})
    if not isinstance(servers, dict):
        raise SetupError(f"{label}: \"{key}\" must be a JSON object; nothing was written.")
    if servers.get(SERVER_NAME) == entry:
        return MergeResult("unchanged", current or "", "")
    status = "updated" if SERVER_NAME in servers else "added"
    document[key] = {**servers, SERVER_NAME: entry}
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    diff = "".join(difflib.unified_diff((current or "").splitlines(keepends=True), text.splitlines(keepends=True), f"{label} (current)", f"{label} (new)"))
    return MergeResult(status, text, diff)


def apply_merge(path: Path, result: MergeResult, prompter: Prompter, out: Callable[[str], None], now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> Path | None:
    """Show the diff, ask, back up the original, and replace the file atomically; return the backup path."""
    if result.status == "unchanged":
        out(f"  {path} already has this server; nothing to change.")
        return None
    out(result.diff.rstrip("\n"))
    if not prompter.confirm(f"Write this change to {path}?", default=True):
        raise SetupError(f"Left {path} unchanged; add the snippet by hand or rerun.")
    backup = None
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(f"{path.name}.{now().strftime('%Y%m%dT%H%M%S%fZ')}.bak")
        backup.write_bytes(path.read_bytes())
        mode = path.stat().st_mode & 0o777
    else:
        mode = 0o600
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(result.text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    out(f"  Wrote {path}" + (f" (backup: {backup})" if backup else ""))
    return backup


def register_file_client(client: str, command: list[str], platform: str, env: Mapping[str, str], prompter: Prompter, out: Callable[[str], None]) -> str:
    path = config_path(client, platform, env)
    if path is None:
        out(f"  {CLIENT_LABEL[client]} config editing is not supported on {platform}; add this snippet to its MCP config:")
        out(snippet(client, command))
        return "printed"
    current = path.read_text(encoding="utf-8") if path.exists() else None
    result = merge_server(current, client, server_entry(client, command), str(path))
    apply_merge(path, result, prompter, out)
    return result.status


def claude_add_command(command: list[str], scope: str) -> list[str]:
    return ["claude", "mcp", "add", "--scope", scope, SERVER_NAME, "--", *command]


@dataclass(frozen=True)
class ClaudeEntry:
    """The fields of `claude mcp get` output that decide whether the entry already matches."""

    scope: str | None
    command: str | None
    args: str


def parse_claude_get(stdout: str) -> ClaudeEntry:
    """Read the Scope, Command, and Args lines; Claude Code prints Args space-joined."""
    fields: dict[str, str] = {}
    for line in stdout.splitlines():
        key, separator, value = line.strip().partition(":")
        if separator and key in {"Scope", "Command", "Args"}:
            fields[key] = value.strip()
    scope_word = fields.get("Scope", "").split(" ", 1)[0].casefold()
    return ClaudeEntry(scope_word if scope_word in CLAUDE_SCOPES else None, fields.get("Command"), fields.get("Args", ""))


def register_claude_code(command: list[str], scope: str, prompter: Prompter, out: Callable[[str], None], which: Callable[[str], str | None], run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> str:
    """Register through the `claude` CLI; print the command when the CLI is absent."""
    add = claude_add_command(command, scope)
    executable = which("claude")
    if executable is None:
        out("  The claude CLI is not on PATH; run this after installing Claude Code:")
        out(f"  {shlex.join(add)}")
        return "printed"
    existing = run([executable, "mcp", "get", SERVER_NAME], capture_output=True, text=True, timeout=60)
    if existing.returncode == 0:
        entry = parse_claude_get(existing.stdout)
        same_command = entry.command == command[0] and entry.args == " ".join(command[1:])
        if same_command and entry.scope in (scope, None):
            out(f"  Claude Code already has '{SERVER_NAME}' with this command ({entry.scope or scope} scope); nothing to change.")
            return "unchanged"
        out(f"  Claude Code already has a different '{SERVER_NAME}' server:")
        out("\n".join(f"    {line}" for line in existing.stdout.strip().splitlines()))
        if not prompter.confirm(f"Replace it with: {shlex.join(command)} ({scope} scope)?", default=True):
            raise SetupError("Left the existing Claude Code server unchanged.")
        old_scope = entry.scope or scope
        removed = run([executable, "mcp", "remove", "--scope", old_scope, SERVER_NAME], capture_output=True, text=True, timeout=60)
        if removed.returncode != 0:
            raise SetupError(f"claude mcp remove --scope {old_scope} failed. Remove it by hand (claude mcp remove {SERVER_NAME}), then rerun.\n{removed.stderr.strip()}")
        status = "updated"
    else:
        if not prompter.confirm(f"Run: {shlex.join(add)}?", default=True):
            raise SetupError("Skipped Claude Code registration.")
        status = "added"
    out(f"  $ {shlex.join(add)}")
    added = run([executable, *add[1:]], capture_output=True, text=True, timeout=60)
    if added.returncode != 0:
        raise SetupError(f"claude mcp add failed:\n{(added.stderr or added.stdout).strip()}")
    out(f"  Registered '{SERVER_NAME}' with Claude Code ({scope} scope). {NO_BACKUP_NOTE}")
    return status

"""Turn flags and answers into a SetupPlan. No step here writes files or starts services.

Every question goes through the Prompter seam, and the model catalog through an
injected `list_models`, so tests drive the whole flow without a console or network.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass, field
from types import MappingProxyType
from pathlib import Path
from typing import Callable, Mapping

from switchplinth.setup.clients import CLAUDE_SCOPES, CLIENTS
from switchplinth.setup.connection import DEFAULT_CREDENTIAL_ENV, DEFAULT_LOCAL_ENDPOINT, PROVIDERS, ConnectionChoice, credential_reference, list_models as catalog_models
from switchplinth.setup.prompts import Prompter, SetupError
from switchplinth.setup.runtime import DEFAULT_PORTS, DEFAULT_PROJECT, REPLACE_FLAG
from switchplinth.setup.workspace import sample_path, validate_repository

MODES = ("local", "docker")
SAMPLE_ANSWER = "sample"
NO_KEY_ANSWER = "none"
WINDOWS = "win32"


@dataclass(frozen=True)
class SetupPlan:
    repo: Path
    sample: bool
    mode: str
    connection: ConnectionChoice
    client: str
    claude_scope: str = "user"
    project: str = DEFAULT_PROJECT
    ports: Mapping[str, int] = field(default_factory=lambda: MappingProxyType(dict(DEFAULT_PORTS)))
    server_command: tuple[str, ...] = ()
    scan: bool = True
    verify: bool = True
    replace_workspace: bool = False

    def describe(self) -> list[str]:
        connection = "none (deterministic extraction)"
        if self.connection.enabled:
            connection = f"{self.connection.provider}, model {self.connection.model}"
            if self.connection.endpoint:
                connection += f", endpoint {self.connection.endpoint}"
            if self.connection.credential_env:
                connection += f", key from ${self.connection.credential_env}"
            if self.connection.reasoning_off:
                connection += ", reasoning off"
        mode = "local stdio MCP (no Docker)" if self.mode == "local" else f"Docker Compose project {self.project} (ports {self.ports['frontend']}/{self.ports['backend']}/{self.ports['qdrant']})"
        lines = [
            f"Repository:  {self.repo}" + (" (bundled food-delivery sample)" if self.sample else ""),
            f"Run mode:    {mode}",
            f"Model:       {connection}",
            f"MCP client:  {self.client}",
            f"MCP command: {' '.join(self.server_command)}",
        ]
        if self.mode == "docker":
            lines.append("             The client runs this local stdio server, not the container's HTTP /mcp.")
        return lines


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", type=Path, help="repository directory with Markdown")
    parser.add_argument("--sample", action="store_true", help="use the bundled food-delivery sample, bootstrapped at $DECISION_DEMO_WORKSPACE/food-delivery (default: ${XDG_CACHE_HOME:-~/.cache}/switchplinth-demo/food-delivery)")
    parser.add_argument("--mode", choices=MODES, help="local: stdio MCP only, no Docker; docker: start the Compose stack")
    parser.add_argument("--provider", choices=PROVIDERS, help="optional model connection (default: none)")
    parser.add_argument("--endpoint", help=f"OpenAI-compatible base URL (default: {DEFAULT_LOCAL_ENDPOINT})")
    parser.add_argument("--model", help="model name for the connection")
    parser.add_argument("--credential-env", help="NAME of the environment variable holding the API key; stored as env:NAME, never the key. Optional for openai-compatible")
    parser.add_argument("--reasoning-off", action="store_true", help="disable model thinking for the connection (generation.reasoning: off)")
    parser.add_argument("--client", choices=CLIENTS, help="register the MCP server with this client; print shows every snippet. On Windows every client prints its snippet and nothing is written")
    parser.add_argument("--claude-scope", choices=CLAUDE_SCOPES, default="user", help="Claude Code scope for `claude mcp add` (default: user)")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help=f"Docker Compose project name (default: {DEFAULT_PROJECT})")
    parser.add_argument(REPLACE_FLAG, action="store_true", help="docker mode: restart the project even when it is already running with a different workspace")
    parser.add_argument("--frontend-port", type=int, default=DEFAULT_PORTS["frontend"], help="docker mode: loopback port for the web app (default: %(default)s)")
    parser.add_argument("--backend-port", type=int, default=DEFAULT_PORTS["backend"], help="docker mode: loopback port for the API and HTTP MCP (default: %(default)s)")
    parser.add_argument("--qdrant-port", type=int, default=DEFAULT_PORTS["qdrant"], help="docker mode: loopback port for Qdrant (default: %(default)s)")
    parser.add_argument("--no-scan", action="store_true", help="skip the first discovery scan")
    parser.add_argument("--no-verify", action="store_true", help="skip the MCP initialize/tools-list check")
    parser.add_argument("--yes", "-y", action="store_true", help="unattended: use flags and defaults, and accept every confirmation")


def default_server_command(which: Callable[[str], str | None] = shutil.which) -> list[str]:
    """Prefer an absolute console script: GUI clients do not inherit the shell PATH."""
    found = which("switchplinth")
    if found:
        return [str(Path(found).absolute())]
    return [sys.executable, "-m", "switchplinth.cli"]


def _answer(prompter: Prompter, flag: str | None, question: str, default: str | None = None, choices: tuple[str, ...] = ()) -> str:
    """A flag answers its question without prompting; otherwise ask with the default."""
    if flag is not None:
        if choices and flag not in choices:
            raise SetupError(f"{question}: {flag!r} is not one of {', '.join(choices)}.")
        return flag
    return prompter.ask(question, default, choices)


def _choose_repo(args: argparse.Namespace, prompter: Prompter, env: Mapping[str, str], out: Callable[[str], None]) -> tuple[Path, bool]:
    if args.sample:
        return sample_path(env).expanduser().resolve(), True
    while True:
        answer = _answer(prompter, str(args.repo) if args.repo else None, f"Repository path, or '{SAMPLE_ANSWER}' for the bundled food-delivery sample", SAMPLE_ANSWER)
        if answer == SAMPLE_ANSWER:
            return sample_path(env).expanduser().resolve(), True
        try:
            root, count = validate_repository(Path(answer))
        except SetupError as exc:
            if args.repo or not prompter.interactive:
                raise
            out(f"  {exc}")
            continue
        out(f"  Found {count} Markdown file(s) under {root}.")
        return root, False


def _choose_connection(args: argparse.Namespace, prompter: Prompter, env: Mapping[str, str], out: Callable[[str], None], list_models: Callable[[ConnectionChoice, Mapping[str, str]], list[str]]) -> ConnectionChoice:
    provider = _answer(prompter, args.provider, "Model connection", "none", PROVIDERS)
    if provider == "none":
        return ConnectionChoice("none")
    endpoint = ""
    credential_env = args.credential_env
    if provider == "openai-compatible":
        endpoint = _answer(prompter, args.endpoint, "OpenAI-compatible endpoint", DEFAULT_LOCAL_ENDPOINT).rstrip("/")
        if credential_env is None and prompter.interactive:
            answer = prompter.ask(f"Name of the environment variable holding the API key, or '{NO_KEY_ANSWER}' for a keyless local server", NO_KEY_ANSWER)
            credential_env = None if answer == NO_KEY_ANSWER else answer
    else:
        credential_env = _answer(prompter, credential_env, "Name of the environment variable holding the API key", DEFAULT_CREDENTIAL_ENV[provider])
    if credential_env:
        credential_env = credential_reference(credential_env).removeprefix("env:")
        if not env.get(credential_env):
            out(f"  Warning: ${credential_env} is not set in this shell; authentication fails until it is.")
    draft = ConnectionChoice(provider, endpoint, "", credential_env)
    models = list_models(draft, env)
    if models:
        out(f"  {len(models)} model(s) available: " + ", ".join(models[:20]) + (" ..." if len(models) > 20 else ""))
    else:
        out("  Could not list models from the provider; enter the model name by hand.")
    model = _answer(prompter, args.model, "Model", models[0] if models else None)
    if models and model not in models:
        out(f"  Note: {model!r} is not in the provider's model list.")
    reasoning_off = args.reasoning_off or (prompter.interactive and prompter.confirm("Turn model reasoning/thinking off (faster on local reasoning models)?", default=False))
    return ConnectionChoice(provider, endpoint, model, credential_env, reasoning_off)


def resolve_plan(
    args: argparse.Namespace,
    prompter: Prompter,
    env: Mapping[str, str],
    out: Callable[[str], None],
    which: Callable[[str], str | None] = shutil.which,
    list_models: Callable[[ConnectionChoice, Mapping[str, str]], list[str]] = catalog_models,
    platform: str = sys.platform,
) -> SetupPlan:
    """Ask only what the flags leave open; validate the repository and connection choices."""
    repo, sample = _choose_repo(args, prompter, env, out)
    mode = _answer(prompter, args.mode, "Run mode: docker (web app, API, HTTP MCP) or local (stdio MCP only)", "local", MODES)
    if mode == "docker" and platform == WINDOWS:
        raise SetupError("Setup does not drive Docker on Windows. Start the stack by hand from the source checkout (docker compose up --build, with DECISION_WORKSPACE_HOST set to your repository), or rerun with --mode local.")
    connection = _choose_connection(args, prompter, env, out, list_models)
    default_client = "claude-code" if which("claude") and platform != WINDOWS else "print"
    client = _answer(prompter, args.client, "Register the MCP server with", default_client, CLIENTS)
    ports = {"frontend": args.frontend_port, "backend": args.backend_port, "qdrant": args.qdrant_port}
    for name, port in ports.items():
        if not 1 <= port <= 65535:
            raise SetupError(f"--{name}-port must be between 1 and 65535.")
    command = (*default_server_command(which), "mcp", "--repo", str(repo))
    return SetupPlan(repo, sample, mode, connection, client, args.claude_scope, args.project, MappingProxyType(ports), command, not args.no_scan, not args.no_verify, args.replace_workspace)

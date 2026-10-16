"""Runtime seam: where the wizard saves the connection, runs diagnostics, and scans.

`LocalRuntime` uses DecisionService in this process with the same cache the
stdio MCP server uses. `DockerRuntime` starts the Compose stack and drives its
HTTP API, so diagnostics run from inside the backend container's network.
"""

from __future__ import annotations

import shlex
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

import httpx

from switchplinth.setup.prompts import SetupError

HEALTH_TIMEOUT_SECONDS = 120
COMPOSE_WAIT_SECONDS = 300
DEFAULT_PORTS = {"frontend": 3000, "backend": 8000, "qdrant": 6333}
# Distinct from the checkout's own `switchplinth` project and scripts/demo.sh's `switchplinth-demo`.
DEFAULT_PROJECT = "switchplinth-setup"
WORKSPACE_MOUNT = "/workspace/repos"
REPLACE_FLAG = "--replace-workspace"


@dataclass(frozen=True)
class ScanSummary:
    documents: int
    passages: int
    decisions: int
    entities: int
    vector_index: str


class Runtime(Protocol):
    def start(self) -> None:
        """Make the runtime ready; idempotent."""

    def save_connection(self, record: dict[str, Any]) -> None:
        """Persist a model_connection through the product's connection path."""

    def diagnose(self, connection_id: str) -> dict[str, Any]:
        """Return the provider diagnostics report for a saved connection."""

    def scan(self) -> ScanSummary:
        """Run deterministic discovery and rebuild indexes."""

    def next_steps(self) -> list[str]:
        """Return commands and URLs to print at the end."""


def summary_from(scan: dict[str, Any], graph: dict[str, Any]) -> ScanSummary:
    return ScanSummary(
        documents=int(scan.get("document_count", 0)),
        passages=int(scan.get("passage_count", 0)),
        decisions=len(graph.get("decisions", [])),
        entities=len(graph.get("entities", [])),
        vector_index=str(scan.get("index", {}).get("vector_index", {}).get("kind", "unknown")),
    )


class LocalRuntime:
    def __init__(self, repo: Path, env: Mapping[str, str], cache: Path | None = None):
        self.repo = repo
        self.env = env
        self.cache = cache
        self._service = None

    @property
    def service(self):
        if self._service is None:
            from switchplinth.cli import cache_for
            from switchplinth.local_vectors import LocalVectorIndex
            from switchplinth.service import DecisionService

            self._service = DecisionService(self.repo, cache_for(self.repo, self.cache, self.env), LocalVectorIndex())
        return self._service

    def start(self) -> None:
        self.service

    def save_connection(self, record: dict[str, Any]) -> None:
        self.service.configure_connection(dict(record))

    def diagnose(self, connection_id: str) -> dict[str, Any]:
        from switchplinth.providers import diagnose

        return diagnose(self.service.connections[connection_id])

    def scan(self) -> ScanSummary:
        result = self.service.scan()
        return summary_from(result, self.service.graph_json(annotate=False))

    def next_steps(self) -> list[str]:
        return []


def compose_env(repo: Path, project: str, ports: Mapping[str, int]) -> dict[str, str]:
    """Interpolation values for docker-compose.yml; no secrets."""
    return {
        "COMPOSE_PROJECT_NAME": project,
        "DECISION_WORKSPACE_HOST": str(repo),
        "DECISION_WORKSPACE_NAME": repo.name,
        "DECISION_FRONTEND_PORT": str(ports["frontend"]),
        "DECISION_BACKEND_PORT": str(ports["backend"]),
        "DECISION_QDRANT_PORT": str(ports["qdrant"]),
    }


def render_env_file(values: Mapping[str, str]) -> str:
    lines = ["# Written by `switchplinth setup`; holds no secrets. Rerun setup to change it."]
    lines += [f"{key}={shlex.quote(value)}" for key, value in values.items()]
    return "\n".join(lines) + "\n"


def render_override(credential_env: str) -> str:
    """Pass one credential variable through from the shell that runs Compose; the value is never written."""
    return f"# Written by `switchplinth setup`: passes {credential_env} from your shell into the backend.\nservices:\n  backend:\n    environment:\n      - {credential_env}\n"


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


@dataclass
class DockerRuntime:
    repo: Path
    checkout: Path
    state_dir: Path
    project: str = DEFAULT_PROJECT
    ports: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_PORTS))
    credential_env: str | None = None
    base_env: Mapping[str, str] = field(default_factory=dict)
    out: Callable[[str], None] = print
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run
    http: Any = httpx
    is_port_free: Callable[[int], bool] = port_free
    # Called with a question when the running project mounts another workspace; None refuses.
    confirm_replace: Callable[[str], bool] | None = None

    @property
    def env_file(self) -> Path:
        return self.state_dir / f"compose-{self.project}.env"

    @property
    def override_file(self) -> Path:
        return self.state_dir / f"compose-{self.project}.override.yml"

    @property
    def api(self) -> str:
        return f"http://127.0.0.1:{self.ports['backend']}"

    def compose_command(self) -> list[str]:
        command = ["docker", "compose", "--project-directory", str(self.checkout), "-f", str(self.checkout / "docker-compose.yml")]
        if self.credential_env:
            command += ["-f", str(self.override_file)]
        return command + ["--env-file", str(self.env_file), "-p", self.project]

    def _write(self, path: Path, text: str) -> None:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.out(f"  Wrote {path}")

    def start(self) -> None:
        if self.run(["docker", "compose", "version"], capture_output=True, text=True).returncode != 0:
            raise SetupError("Docker with Compose v2 is required for --mode docker (https://docs.docker.com/get-docker/); or rerun with --mode local.")
        # Check before writing anything, so a refusal leaves the env file matching the running stack.
        running = self.run(["docker", "compose", "-p", self.project, "ps", "-q"], capture_output=True, text=True)
        if running.stdout.strip():
            self._check_running_workspace()
        else:
            busy = [f"{name} {port}" for name, port in self.ports.items() if not self.is_port_free(port)]
            if busy:
                raise SetupError(f"Loopback ports in use: {', '.join(busy)}. Stop the other service or pass --frontend-port/--backend-port/--qdrant-port.")
        values = compose_env(self.repo, self.project, self.ports)
        self._write(self.env_file, render_env_file(values))
        if self.credential_env:
            self._write(self.override_file, render_override(self.credential_env))
        command = self.compose_command() + ["up", "-d", "--build", "--wait", "--wait-timeout", str(COMPOSE_WAIT_SECONDS)]
        self.out(f"  $ {shlex.join(command)}")
        started = self.run(command, env={**self.base_env, **values}, capture_output=True, text=True)
        if started.returncode != 0:
            tail = "\n".join((started.stderr or started.stdout).strip().splitlines()[-15:])
            raise SetupError(f"docker compose up failed:\n{tail}")
        self._wait_healthy()

    def running_workspace(self) -> str | None:
        """Return the host directory the project's backend container mounts as the workspace, if any."""
        labels = ["--filter", f"label=com.docker.compose.project={self.project}", "--filter", "label=com.docker.compose.service=backend"]
        found = self.run(["docker", "ps", "-aq", *labels], capture_output=True, text=True)
        container = next(iter(found.stdout.split()), None)
        if container is None:
            return None
        template = f'{{{{range .Mounts}}}}{{{{if eq .Destination "{WORKSPACE_MOUNT}"}}}}{{{{.Source}}}}{{{{end}}}}{{{{end}}}}'
        inspected = self.run(["docker", "inspect", "--format", template, container], capture_output=True, text=True)
        return inspected.stdout.strip() or None

    def _check_running_workspace(self) -> None:
        """Refuse to remount a running project on another workspace unless the user agrees."""
        current = self.running_workspace()
        if current is None or Path(current) == self.repo:
            return
        question = f"Compose project {self.project} is already running with workspace {current}. Restart it on {self.repo}?"
        if self.confirm_replace is not None and self.confirm_replace(question):
            return
        raise SetupError(f"Compose project {self.project} is already running with workspace {current}; left it unchanged. Pass {REPLACE_FLAG} to restart it on {self.repo}, or choose another --project.")

    def _wait_healthy(self) -> None:
        deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
        while True:
            try:
                if self.http.get(f"{self.api}/health", timeout=3).status_code == 200:
                    self.out(f"  Backend healthy at {self.api}")
                    return
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise SetupError(f"Backend did not report healthy at {self.api}/health within {HEALTH_TIMEOUT_SECONDS}s; check: docker compose -p {self.project} logs backend")
            time.sleep(2)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.http.request(method, f"{self.api}{path}", timeout=kwargs.pop("timeout", 60), **kwargs)
        except httpx.HTTPError as exc:
            raise SetupError(f"{method} {self.api}{path} failed: {exc}") from exc
        if response.status_code >= 400:
            raise SetupError(f"{method} {self.api}{path} returned HTTP {response.status_code}: {response.text[:300]}")
        return response.json()

    def save_connection(self, record: dict[str, Any]) -> None:
        self._request("POST", "/api/v1/connections", json=record)

    def diagnose(self, connection_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/connections/{connection_id}/test")

    def scan(self) -> ScanSummary:
        result = self._request("POST", "/api/v1/discovery/scan", timeout=600)
        return summary_from(result, self._request("GET", "/api/v1/graph"))

    def next_steps(self) -> list[str]:
        compose = shlex.join(self.compose_command())
        return [
            f"Web app:   http://localhost:{self.ports['frontend']}",
            f"API docs:  {self.api}/docs",
            f"HTTP MCP:  {self.api}/mcp",
            f"Logs:      {compose} logs backend",
            f"Stop:      {compose} down",
        ]

"""Provider-neutral generation controls on model connections."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from switchplinth.api import create_app
from switchplinth.domain import DomainError
from switchplinth.providers import extract_with_litellm, litellm_generation_kwargs, propose_delta_with_litellm
from switchplinth.repository import PortableRepository
from switchplinth.service import DecisionService


class _ChatStub(BaseHTTPRequestHandler):
    """Record chat-completion request bodies and answer with a JSON object."""

    bodies: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        self.bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        payload = json.dumps({
            "id": "stub", "object": "chat.completion", "created": 0, "model": "stub-model",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{\"entities\": []}"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def chat_stub() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    bodies: list[dict[str, Any]] = []
    handler = type("Handler", (_ChatStub,), {"bodies": bodies})
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", bodies
    finally:
        server.shutdown()


def _connection(endpoint: str, **extra: Any) -> dict[str, Any]:
    return {"id": "local", "provider": "openai_compatible", "endpoint": endpoint, "model": "stub-model", **extra}


def test_reasoning_off_reaches_openai_compatible_endpoint_as_reasoning_effort_none(chat_stub: tuple[str, list[dict[str, Any]]]) -> None:
    endpoint, bodies = chat_stub

    result = extract_with_litellm(_connection(endpoint, generation={"reasoning": "off", "max_output_tokens": 2048}), "Passage.")

    assert result == {"entities": []}
    assert bodies[-1]["reasoning_effort"] == "none"
    assert bodies[-1]["max_tokens"] == 2048


def test_reasoning_level_and_proposal_share_the_same_generation_mapping(chat_stub: tuple[str, list[dict[str, Any]]]) -> None:
    endpoint, bodies = chat_stub

    propose_delta_with_litellm(_connection(endpoint, generation={"reasoning": "low"}), {"id": "d"}, {"id": "o"}, "change", {})

    assert bodies[-1]["reasoning_effort"] == "low"
    assert "max_tokens" not in bodies[-1]


def test_connection_without_generation_sends_no_generation_controls(chat_stub: tuple[str, list[dict[str, Any]]]) -> None:
    endpoint, bodies = chat_stub

    extract_with_litellm(_connection(endpoint), "Passage.")

    assert "reasoning_effort" not in bodies[-1]
    assert "max_tokens" not in bodies[-1]


def test_saved_connection_keeps_generation_and_omits_blank_generation_fields(tmp_path: Path) -> None:
    service = DecisionService(tmp_path, tmp_path / "cache")
    client = TestClient(create_app(service))

    saved = client.post("/api/v1/connections", json={"id": "qwen", "provider": "openai_compatible", "endpoint": "http://localhost:1/v1", "model": "qwen", "generation": {"reasoning": "off", "max_output_tokens": None}})
    blank = client.post("/api/v1/connections", json={"id": "plain", "provider": "openai_compatible", "endpoint": "http://localhost:1/v1", "model": "plain", "generation": {"reasoning": "", "max_output_tokens": None}})

    assert saved.status_code == 200
    assert saved.json()["generation"] == {"reasoning": "off"}
    assert blank.status_code == 200
    assert "generation" not in blank.json()
    on_disk = {path.stem: yaml.safe_load(path.read_text(encoding="utf-8")) for path in (tmp_path / ".decision" / "connections").glob("*.yaml")}
    assert on_disk["qwen"]["generation"] == {"reasoning": "off"}
    assert "generation" not in on_disk["plain"]
    assert DecisionService(tmp_path, tmp_path / "cache").connections["qwen"]["generation"] == {"reasoning": "off"}


@pytest.mark.parametrize("generation", [{"reasoning": "maximum"}, {"max_output_tokens": 0}, {"max_output_tokens": "many"}, {"temperature": 0.2}])
def test_invalid_generation_is_rejected_before_writing(tmp_path: Path, generation: dict[str, Any]) -> None:
    service = DecisionService(tmp_path, tmp_path / "cache")

    response = TestClient(create_app(service)).post("/api/v1/connections", json={"id": "bad", "provider": "openai_compatible", "endpoint": "http://localhost:1/v1", "model": "m", "generation": generation})

    assert response.status_code == 422
    assert not (tmp_path / ".decision" / "connections" / "bad.yaml").exists()


def test_invalid_generation_in_yaml_fails_read_even_with_permissive_overlay_schema(tmp_path: Path) -> None:
    DecisionService(tmp_path, tmp_path / "cache")
    schema_path = tmp_path / ".decision" / "schema" / "record-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["properties"].pop("generation", None)
    schema.get("$defs", {}).pop("generation", None)
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    connections = tmp_path / ".decision" / "connections"
    connections.mkdir(parents=True, exist_ok=True)
    (connections / "bad.yaml").write_text(yaml.safe_dump({"schema_version": "decision/v1", "record_type": "model_connection", "id": "bad", "provider": "openai_compatible", "model": "m", "generation": {"reasoning": "sometimes"}}), encoding="utf-8")

    with pytest.raises(DomainError, match="generation"):
        PortableRepository(tmp_path).records("connections")


def test_generation_is_only_valid_on_model_connections(tmp_path: Path) -> None:
    DecisionService(tmp_path, tmp_path / "cache")

    with pytest.raises(DomainError, match="generation"):
        PortableRepository(tmp_path).save("entities", {"schema_version": "decision/v1", "record_type": "entity", "id": "svc", "kind": "service", "name": "Svc", "generation": {"reasoning": "off"}})


def test_resaving_connection_without_generation_keeps_stored_generation(tmp_path: Path) -> None:
    service = DecisionService(tmp_path, tmp_path / "cache")
    client = TestClient(create_app(service))
    base = {"id": "qwen", "provider": "openai_compatible", "endpoint": "http://localhost:1/v1", "model": "qwen"}
    client.post("/api/v1/connections", json={**base, "generation": {"reasoning": "off", "max_output_tokens": 4096}})

    resaved = client.post("/api/v1/connections", json={**base, "name": "Renamed in the form"})

    assert resaved.status_code == 200
    assert resaved.json()["generation"] == {"reasoning": "off", "max_output_tokens": 4096}
    assert DecisionService(tmp_path, tmp_path / "cache").connections["qwen"]["generation"] == {"reasoning": "off", "max_output_tokens": 4096}


def test_explicit_empty_generation_clears_stored_generation(tmp_path: Path) -> None:
    service = DecisionService(tmp_path, tmp_path / "cache")
    client = TestClient(create_app(service))
    base = {"id": "qwen", "provider": "openai_compatible", "endpoint": "http://localhost:1/v1", "model": "qwen"}
    client.post("/api/v1/connections", json={**base, "generation": {"reasoning": "off"}})

    cleared = client.post("/api/v1/connections", json={**base, "generation": {}})

    assert cleared.status_code == 200
    assert "generation" not in cleared.json()
    assert "generation" not in DecisionService(tmp_path, tmp_path / "cache").connections["qwen"]


def test_anthropic_reasoning_off_sends_no_reasoning_effort() -> None:
    connection = {"id": "claude", "provider": "anthropic", "model": "claude-model", "generation": {"reasoning": "off", "max_output_tokens": 1024}}

    assert litellm_generation_kwargs(connection) == {"max_tokens": 1024}
    assert litellm_generation_kwargs({**connection, "generation": {"reasoning": "high"}}) == {"reasoning_effort": "high"}

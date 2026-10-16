"""Connection-save semantics the settings form relies on for generation settings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from switchplinth.api import create_app
from switchplinth.service import DecisionService


def _connection(**extra: Any) -> dict[str, Any]:
    return {"id": "local", "name": "Local", "provider": "openai_compatible", "endpoint": "http://localhost:1/v1", "model": "m", **extra}


def _stored(tmp_path: Path) -> dict[str, Any] | None:
    return DecisionService(tmp_path, tmp_path / "cache").connections["local"].get("generation")


def test_omitted_generation_keeps_the_stored_settings(tmp_path: Path) -> None:
    client = TestClient(create_app(DecisionService(tmp_path, tmp_path / "cache")))
    client.post("/api/v1/connections", json=_connection(generation={"reasoning": "low", "max_output_tokens": 512, "request_timeout_seconds": 45}))

    assert client.post("/api/v1/connections", json=_connection(model="m2")).status_code == 200

    assert _stored(tmp_path) == {"reasoning": "low", "max_output_tokens": 512, "request_timeout_seconds": 45}
    listed = client.get("/api/v1/connections").json()
    assert listed[0]["generation"] == {"reasoning": "low", "max_output_tokens": 512, "request_timeout_seconds": 45}


def test_merged_generation_replaces_only_the_timeout(tmp_path: Path) -> None:
    client = TestClient(create_app(DecisionService(tmp_path, tmp_path / "cache")))
    client.post("/api/v1/connections", json=_connection(generation={"reasoning": "low", "max_output_tokens": 512, "request_timeout_seconds": 45}))

    client.post("/api/v1/connections", json=_connection(generation={"reasoning": "low", "max_output_tokens": 512, "request_timeout_seconds": 90}))
    assert _stored(tmp_path) == {"reasoning": "low", "max_output_tokens": 512, "request_timeout_seconds": 90}

    # A blank timeout sends the other stored keys without request_timeout_seconds.
    client.post("/api/v1/connections", json=_connection(generation={"reasoning": "low", "max_output_tokens": 512}))
    assert _stored(tmp_path) == {"reasoning": "low", "max_output_tokens": 512}


def test_empty_generation_clears_a_timeout_only_setting(tmp_path: Path) -> None:
    client = TestClient(create_app(DecisionService(tmp_path, tmp_path / "cache")))
    client.post("/api/v1/connections", json=_connection(generation={"request_timeout_seconds": 45}))

    client.post("/api/v1/connections", json=_connection(generation={}))

    assert _stored(tmp_path) is None
    assert "generation" not in client.get("/api/v1/connections").json()[0]

"""Portable request timeout for LiteLLM completions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import litellm
import pytest
from fastapi.testclient import TestClient

from switchplinth.api import create_app
from switchplinth.providers import DEFAULT_REQUEST_TIMEOUT_SECONDS, extract_with_litellm, propose_delta_with_litellm
from switchplinth.service import DecisionService


@pytest.fixture
def completion_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])

    monkeypatch.setattr(litellm, "completion", completion)
    return calls


def _connection(**extra: Any) -> dict[str, Any]:
    return {"id": "local", "provider": "openai_compatible", "endpoint": "http://localhost:1/v1", "model": "m", **extra}


def test_completions_use_the_default_timeout_without_configuration(completion_calls: list[dict[str, Any]]) -> None:
    extract_with_litellm(_connection(), "Passage.")
    propose_delta_with_litellm(_connection(generation={"reasoning": "off"}), {}, {}, "change", {})

    assert DEFAULT_REQUEST_TIMEOUT_SECONDS == 600
    assert [call["timeout"] for call in completion_calls] == [600, 600]


def test_configured_request_timeout_reaches_extraction_and_proposal(completion_calls: list[dict[str, Any]]) -> None:
    connection = _connection(generation={"request_timeout_seconds": 1800})

    extract_with_litellm(connection, "Passage.")
    propose_delta_with_litellm(connection, {}, {}, "change", {})

    assert [call["timeout"] for call in completion_calls] == [1800, 1800]
    assert "request_timeout_seconds" not in completion_calls[0]


def test_saved_connection_keeps_request_timeout(tmp_path: Path) -> None:
    client = TestClient(create_app(DecisionService(tmp_path, tmp_path / "cache")))

    saved = client.post("/api/v1/connections", json={**_connection(), "generation": {"reasoning": "off", "request_timeout_seconds": 900}})

    assert saved.status_code == 200
    assert DecisionService(tmp_path, tmp_path / "cache").connections["local"]["generation"] == {"reasoning": "off", "request_timeout_seconds": 900}


@pytest.mark.parametrize("timeout", [0, -5, "slow", True])
def test_invalid_request_timeout_is_rejected_before_writing(tmp_path: Path, timeout: Any) -> None:
    client = TestClient(create_app(DecisionService(tmp_path, tmp_path / "cache")))

    response = client.post("/api/v1/connections", json={**_connection(id="bad"), "generation": {"request_timeout_seconds": timeout}})

    assert response.status_code == 422
    assert not (tmp_path / ".decision" / "connections" / "bad.yaml").exists()

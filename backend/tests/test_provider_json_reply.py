"""Model replies wrapped in one Markdown code fence still parse as JSON."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import litellm
import pytest

from switchplinth.providers import ProviderError, extract_with_litellm, parse_json_reply, propose_delta_with_litellm

CONNECTION = {"id": "local", "provider": "openai_compatible", "endpoint": "http://localhost:1/v1", "model": "m"}


@pytest.mark.parametrize(
    "content",
    [
        '{"a": 1}',
        '  {"a": 1}\n',
        '```json\n{"a": 1}\n```',
        '```\n{"a": 1}\n```',
        '\n```json\n{"a": 1}\n```\n',
    ],
)
def test_bare_or_fenced_json_parses(content: str) -> None:
    assert parse_json_reply(content) == {"a": 1}


@pytest.mark.parametrize("content", ["", None, "Here is the JSON: {\"a\": 1}", "```json\n{\"a\": 1}", "```json {\"a\": 1}```"])
def test_anything_else_is_rejected(content: str | None) -> None:
    with pytest.raises(json.JSONDecodeError):
        parse_json_reply(content)


def _reply(monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    def completion(**_: Any) -> Any:
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(litellm, "completion", completion)


def test_extraction_and_proposal_accept_a_fenced_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    _reply(monkeypatch, '```json\n{"decisions": []}\n```')
    assert extract_with_litellm(CONNECTION, "Passage.") == {"decisions": []}
    assert propose_delta_with_litellm(CONNECTION, {}, {}, "change", {}) == {"decisions": []}


def test_extraction_still_fails_on_prose(monkeypatch: pytest.MonkeyPatch) -> None:
    _reply(monkeypatch, "I could not find any decisions.")
    with pytest.raises(ProviderError, match="JSONDecodeError"):
        extract_with_litellm(CONNECTION, "Passage.")

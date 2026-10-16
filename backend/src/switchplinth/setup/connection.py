"""Model connection choices turned into provider-neutral `model_connection` records.

Credentials are stored only as `env:NAME` references; this module rejects
anything that is not a valid environment variable name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit

import httpx

from switchplinth.providers import HOSTED_ENDPOINTS
from switchplinth.setup.prompts import SetupError

PROVIDERS = ("none", "openai-compatible", "openai", "anthropic")
RECORD_PROVIDER = {"openai-compatible": "openai_compatible", "openai": "openai", "anthropic": "anthropic"}
DEFAULT_CREDENTIAL_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
DEFAULT_LOCAL_ENDPOINT = "http://localhost:8080/v1"
CONNECTION_ID = {"openai-compatible": "local-openai-compatible", "openai": "openai", "anthropic": "anthropic"}
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
DOCKER_HOST_ALIAS = "host.docker.internal"


@dataclass(frozen=True)
class ConnectionChoice:
    provider: str
    endpoint: str = ""
    model: str = ""
    credential_env: str | None = None
    reasoning_off: bool = False

    @property
    def enabled(self) -> bool:
        return self.provider != "none"


def credential_reference(name: str | None) -> str | None:
    """Return `env:NAME` for a variable name; refuse values that look like secrets."""
    if not name:
        return None
    candidate = name[4:] if name.startswith("env:") else name
    if not ENV_NAME.match(candidate):
        raise SetupError("Give the NAME of an environment variable that holds the key (for example OPENAI_API_KEY), not the key itself.")
    return f"env:{candidate}"


def endpoint_for_docker(endpoint: str) -> str:
    """Containers reach host loopback services through host.docker.internal."""
    parts = urlsplit(endpoint)
    if parts.hostname not in LOOPBACK_HOSTS:
        return endpoint
    netloc = DOCKER_HOST_ALIAS + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def connection_record(choice: ConnectionChoice, docker: bool = False) -> dict[str, Any]:
    """Build the record that DecisionService.configure_connection and POST /api/v1/connections accept."""
    if not choice.enabled:
        raise SetupError("No model connection was chosen.")
    if choice.provider not in RECORD_PROVIDER:
        raise SetupError(f"Unknown provider {choice.provider!r}; choose one of {', '.join(PROVIDERS)}.")
    if not choice.model:
        raise SetupError("A model connection needs a model name (--model).")
    record: dict[str, Any] = {
        "id": CONNECTION_ID[choice.provider],
        "name": f"{choice.provider} ({choice.model})",
        "provider": RECORD_PROVIDER[choice.provider],
        "model": choice.model,
        "capabilities": {},
    }
    if choice.provider == "openai-compatible":
        if not choice.endpoint:
            raise SetupError("A local OpenAI-compatible connection needs an endpoint (--endpoint).")
        record["endpoint"] = endpoint_for_docker(choice.endpoint) if docker else choice.endpoint.rstrip("/")
    else:
        record["endpoint"] = ""
    reference = credential_reference(choice.credential_env)
    if choice.provider in HOSTED_ENDPOINTS and reference is None:
        raise SetupError(f"{choice.provider} needs a credential environment variable (--credential-env {DEFAULT_CREDENTIAL_ENV[choice.provider]}).")
    if reference:
        record["credential_ref"] = reference
    if choice.reasoning_off:
        record["generation"] = {"reasoning": "off"}
    return record


def list_models(choice: ConnectionChoice, env: Mapping[str, str], get: Callable[..., Any] = httpx.get) -> list[str]:
    """Return model IDs from the provider catalog; an empty list when it is unreachable."""
    endpoint = HOSTED_ENDPOINTS.get(choice.provider, choice.endpoint).rstrip("/")
    reference = credential_reference(choice.credential_env)
    secret = env.get(reference[4:]) if reference else None
    if choice.provider == "anthropic":
        if not secret:
            return []
        url, headers = f"{endpoint}/v1/models", {"x-api-key": secret, "anthropic-version": "2023-06-01"}
    else:
        if choice.provider == "openai" and not secret:
            return []
        url, headers = f"{endpoint}/models", ({"Authorization": f"Bearer {secret}"} if secret else {})
    try:
        response = get(url, headers=headers, timeout=5)
        response.raise_for_status()
        return [str(item["id"]) for item in response.json().get("data", []) if item.get("id")]
    except Exception:
        return []

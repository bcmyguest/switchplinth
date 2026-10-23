"""Provider-neutral inference connections and transparent diagnostics."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx


CAPABILITIES = ("authentication", "endpoint", "model", "structured_output", "embeddings", "streaming")
HOSTED_ENDPOINTS = {"openai": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com"}
EMBEDDINGS_NOT_CONFIGURED = "No embedding model is configured for this connection."
KEYLESS_OPENAI_COMPATIBLE_API_KEY = "no-key-required"
# Portable reasoning levels mapped to LiteLLM reasoning_effort. "none" disables
# model thinking on OpenAI-compatible servers (e.g. llama.cpp chat templates) and
# becomes think=false for Ollama.
REASONING_EFFORT = {"off": "none", "low": "low", "medium": "medium", "high": "high"}
# Seconds LiteLLM waits for one completion unless generation.request_timeout_seconds
# overrides it. Local models can need minutes for a full-corpus extraction.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 600


class ProviderError(RuntimeError):
    pass


def resolve_secret(reference: str | None) -> str | None:
    if not reference or not reference.startswith("env:"):
        return None
    return os.environ.get(reference[4:])


def litellm_model(connection: dict[str, Any]) -> str:
    """Translate provider-neutral connection types to LiteLLM model prefixes."""
    provider = connection.get("provider", "")
    model = str(connection.get("model", ""))
    if "/" in model:
        return model
    match provider:
        case "openai_compatible" | "lm_studio":
            return f"openai/{model}"
        case "ollama":
            return f"ollama_chat/{model}"
        case "anthropic":
            return f"anthropic/{model}"
        case "openai":
            return f"openai/{model}"
        case _:
            return model


def provider_endpoint(connection: dict[str, Any]) -> str:
    """Return the provider's effective endpoint, ignoring stale local URLs for hosted providers."""
    provider = connection.get("provider", "")
    if provider in HOSTED_ENDPOINTS:
        return HOSTED_ENDPOINTS[provider]
    return str(connection.get("endpoint", "")).rstrip("/")


def litellm_api_base(connection: dict[str, Any]) -> str | None:
    """Pass custom endpoints to LiteLLM only for providers that use them."""
    if connection.get("provider") in HOSTED_ENDPOINTS:
        return None
    return provider_endpoint(connection) or None


def litellm_api_key(connection: dict[str, Any]) -> str | None:
    """Resolve configured credentials, allowing keyless local OpenAI-compatible endpoints."""
    reference = connection.get("credential_ref")
    if reference:
        return resolve_secret(reference)
    if connection.get("provider") == "openai_compatible":
        return KEYLESS_OPENAI_COMPATIBLE_API_KEY
    return None


def litellm_generation_kwargs(connection: dict[str, Any]) -> dict[str, Any]:
    """Translate the optional portable generation block to LiteLLM completion arguments."""
    generation = connection.get("generation") or {}
    kwargs: dict[str, Any] = {}
    reasoning = generation.get("reasoning")
    # Anthropic thinking is off unless requested, so "off" sends nothing there.
    if reasoning in REASONING_EFFORT and not (reasoning == "off" and connection.get("provider") == "anthropic"):
        kwargs["reasoning_effort"] = REASONING_EFFORT[reasoning]
    if generation.get("max_output_tokens"):
        kwargs["max_tokens"] = generation["max_output_tokens"]
    return kwargs


def litellm_request_timeout(connection: dict[str, Any]) -> float:
    """Return the portable per-request completion timeout in seconds."""
    generation = connection.get("generation") or {}
    return generation.get("request_timeout_seconds") or DEFAULT_REQUEST_TIMEOUT_SECONDS


def litellm_embedding_model(connection: dict[str, Any]) -> str:
    """Map a configured embedding model to its provider-specific LiteLLM name."""
    model = str(connection.get("embedding_model", ""))
    provider = connection.get("provider", "")
    if "/" in model:
        return model
    match provider:
        case "openai_compatible" | "lm_studio" | "openai":
            return f"openai/{model}"
        case "ollama":
            return f"ollama/{model}"
        case _:
            raise ProviderError(f"Provider {provider!r} has no V0 embedding adapter.")


def embed_with_litellm(connection: dict[str, Any], text: str) -> list[float]:
    """Create one validated embedding using the configured inference provider."""
    try:
        import litellm
        result = litellm.embedding(
            model=litellm_embedding_model(connection),
            input=[text],
            api_base=litellm_api_base(connection),
            api_key=litellm_api_key(connection),
        )
        vector = result.data[0]["embedding"]
        if not isinstance(vector, list) or not vector or any(not isinstance(value, (int, float)) for value in vector):
            raise ProviderError("Embedding provider returned an empty or invalid vector.")
        return [float(value) for value in vector]
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"LiteLLM embedding failed: {type(exc).__name__}: {exc}") from exc


def diagnose(connection: dict[str, Any]) -> dict[str, Any]:
    """Probe compatible OpenAI endpoints, explicitly reporting every capability."""
    started = time.monotonic()
    provider = connection.get("provider", "mock")
    if provider == "mock":
        return {"id": connection.get("id", "mock"), "latency_ms": 0, "capabilities": {name: {"status": "supported" if name in {"endpoint", "model", "structured_output"} else "unsupported", "raw_error": None, "normalized_error": None} for name in CAPABILITIES}}
    if provider not in {"openai_compatible", "ollama", "lm_studio", "openai", "anthropic"}:
        return {"id": connection.get("id"), "latency_ms": None, "capabilities": {name: {"status": "error", "raw_error": f"Provider adapter {provider!r} is not available in V0.", "normalized_error": "unsupported_provider"} for name in CAPABILITIES}}
    secret = resolve_secret(connection.get("credential_ref"))
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    endpoint = provider_endpoint(connection)
    if provider == "anthropic":
        headers = {"x-api-key": secret, "anthropic-version": "2023-06-01"} if secret else headers
    raw_error = None
    models: list[str] = []
    status = "supported"
    endpoint_reachable = False
    try:
        models_path = "/v1/models" if provider == "anthropic" else "/models"
        response = httpx.get(f"{endpoint}{models_path}", headers=headers, timeout=5)
        endpoint_reachable = True
        if response.status_code >= 400:
            raw_error = f"HTTP {response.status_code}: {response.text[:300]}"
            status = "error"
        else:
            models = [item.get("id", "") for item in response.json().get("data", [])]
    except Exception as exc:
        raw_error = f"{type(exc).__name__}: {exc}"
        status = "error"
    model_exists = connection.get("model") in models if models else False
    latency = round((time.monotonic() - started) * 1000)
    probe_capabilities: dict[str, dict[str, Any]] = {}
    if provider == "anthropic":
        probe_capabilities["structured_output"] = {"status": "error", "raw_error": "V0 has no Anthropic-specific structured-output probe; capability is unverified.", "normalized_error": "capability_probe_not_implemented"}
        probe_capabilities["streaming"] = {"status": "error", "raw_error": "V0 has no Anthropic-specific streaming probe; capability is unverified.", "normalized_error": "capability_probe_not_implemented"}
        probe_capabilities["embeddings"] = {"status": "unsupported", "raw_error": "V0 embeddings probe uses the OpenAI-compatible embeddings endpoint.", "normalized_error": "probe_not_supported_for_protocol"}
    elif raw_error or not model_exists:
        normalized_failure = "invalid_credentials" if raw_error and ("401" in raw_error or "403" in raw_error) else ("connection_failed" if not endpoint_reachable else "model_unavailable")
        state = "error" if raw_error else "unsupported"
        probe_capabilities["structured_output"] = {"status": state, "raw_error": raw_error or "Configured model was not returned by the endpoint.", "normalized_error": normalized_failure}
        probe_capabilities["streaming"] = {"status": state, "raw_error": raw_error or "Configured model was not returned by the endpoint.", "normalized_error": normalized_failure}
        if connection.get("capabilities", {}).get("embeddings"):
            if not connection.get("embedding_model"):
                probe_capabilities["embeddings"] = {"status": "unsupported", "raw_error": EMBEDDINGS_NOT_CONFIGURED, "normalized_error": "embedding_model_not_configured"}
            else:
                probe_capabilities["embeddings"] = {"status": state, "raw_error": raw_error or f"Configured embedding model {connection['embedding_model']!r} could not be verified because the model catalog is unavailable or the chat model is unavailable.", "normalized_error": normalized_failure}
    else:
        probe_url = f"{endpoint}/chat/completions"
        common = {"model": connection["model"], "messages": [{"role": "user", "content": "Reply with a short JSON object."}], "max_tokens": 16}
        try:
            structured_response = httpx.post(probe_url, headers=headers, json={**common, "response_format": {"type": "json_object"}}, timeout=5)
            if structured_response.status_code < 300:
                probe_capabilities["structured_output"] = {"status": "supported", "raw_error": None, "normalized_error": None}
            else:
                raw = f"HTTP {structured_response.status_code}: {structured_response.text[:300]}"
                probe_capabilities["structured_output"] = {"status": "unsupported" if structured_response.status_code in {400, 404, 422} else "error", "raw_error": raw, "normalized_error": "structured_output_unsupported" if structured_response.status_code in {400, 404, 422} else "capability_probe_failed"}
        except Exception as exc:
            probe_capabilities["structured_output"] = {"status": "error", "raw_error": f"{type(exc).__name__}: {exc}", "normalized_error": "capability_probe_failed"}
        try:
            streaming_response = httpx.post(probe_url, headers=headers, json={**common, "stream": True}, timeout=5)
            if streaming_response.status_code < 300 and ("text/event-stream" in streaming_response.headers.get("content-type", "") or "data: [DONE]" in streaming_response.text):
                probe_capabilities["streaming"] = {"status": "supported", "raw_error": None, "normalized_error": None}
            elif streaming_response.status_code in {400, 404, 422}:
                probe_capabilities["streaming"] = {"status": "unsupported", "raw_error": f"HTTP {streaming_response.status_code}: {streaming_response.text[:300]}", "normalized_error": "streaming_unsupported"}
            else:
                probe_capabilities["streaming"] = {"status": "error", "raw_error": f"HTTP {streaming_response.status_code}: endpoint did not return a stream", "normalized_error": "invalid_stream_response"}
        except Exception as exc:
            probe_capabilities["streaming"] = {"status": "error", "raw_error": f"{type(exc).__name__}: {exc}", "normalized_error": "capability_probe_failed"}
        if connection.get("capabilities", {}).get("embeddings"):
            embedding_model = connection.get("embedding_model")
            if not embedding_model:
                probe_capabilities["embeddings"] = {"status": "unsupported", "raw_error": EMBEDDINGS_NOT_CONFIGURED, "normalized_error": "embedding_model_not_configured"}
            elif embedding_model not in models:
                probe_capabilities["embeddings"] = {"status": "unsupported", "raw_error": f"Embedding model {embedding_model!r} was not returned by the endpoint model catalog.", "normalized_error": "embedding_model_unavailable"}
            else:
                try:
                    embedding_response = httpx.post(f"{endpoint}/embeddings", headers=headers, json={"model": embedding_model, "input": "embedding diagnostic"}, timeout=5)
                    if embedding_response.status_code < 300:
                        body = embedding_response.json()
                        valid_vector = bool(body.get("data")) and isinstance(body["data"][0].get("embedding"), list) and bool(body["data"][0]["embedding"])
                        probe_capabilities["embeddings"] = {"status": "supported" if valid_vector else "error", "raw_error": None if valid_vector else "HTTP response did not contain a non-empty embedding vector.", "normalized_error": None if valid_vector else "invalid_embedding_response"}
                    else:
                        raw = f"HTTP {embedding_response.status_code}: {embedding_response.text[:300]}"
                        normalized = "invalid_credentials" if embedding_response.status_code in {401, 403} else ("embeddings_unsupported" if embedding_response.status_code in {400, 404, 422} else "capability_probe_failed")
                        probe_capabilities["embeddings"] = {"status": "error" if embedding_response.status_code not in {400, 404, 422} else "unsupported", "raw_error": raw, "normalized_error": normalized}
                except Exception as exc:
                    probe_capabilities["embeddings"] = {"status": "error", "raw_error": f"{type(exc).__name__}: {exc}", "normalized_error": "capability_probe_failed"}
    return {"id": connection.get("id"), "latency_ms": latency, "capabilities": {
        "authentication": {"status": "error" if raw_error and ("401" in raw_error or "403" in raw_error) else ("error" if not endpoint_reachable else "supported"), "raw_error": raw_error, "normalized_error": "invalid_credentials" if raw_error and ("401" in raw_error or "403" in raw_error) else ("connection_failed" if not endpoint_reachable else None)},
        "endpoint": {"status": "supported" if endpoint_reachable else "error", "raw_error": raw_error, "normalized_error": None if endpoint_reachable else "endpoint_unreachable"},
        "model": {"status": "supported" if model_exists else ("error" if models or (raw_error and ("401" in raw_error or "403" in raw_error)) else "unsupported"), "raw_error": None if model_exists else (raw_error or (f"Model {connection.get('model')!r} not returned by endpoint." if models else "Model catalog was not available.")), "normalized_error": None if model_exists else ("invalid_credentials" if raw_error and ("401" in raw_error or "403" in raw_error) else "model_unavailable")},
        "structured_output": probe_capabilities["structured_output"],
        "embeddings": probe_capabilities.get("embeddings", {"status": "unsupported", "raw_error": EMBEDDINGS_NOT_CONFIGURED, "normalized_error": "embedding_model_not_configured"}),
        "streaming": probe_capabilities["streaming"],
    }}


def parse_json_reply(content: str | None) -> Any:
    """Parse a model reply as JSON. Local models often wrap JSON in one Markdown code fence even when JSON output
    is requested, so a single surrounding fence (```json or ```) is removed first; anything else must be bare JSON."""
    text = (content or "").strip()
    if text.startswith("```") and text.endswith("```") and "\n" in text:
        text = text[text.index("\n") + 1 : -3].strip()
    return json.loads(text)


def extract_with_litellm(connection: dict[str, Any], text: str) -> dict[str, Any]:
    """Run a structured extraction prompt through LiteLLM when configured."""
    try:
        import litellm
        result = litellm.completion(model=litellm_model(connection), messages=[{"role": "system", "content": "Extract architecture entities, relationships, consequences, and decisions from arbitrary repository Markdown passages. Return JSON: {entities:[{name,kind,aliases:[...],confidence,alias_confidence,evidence_quote}],relationships:[{from_name,to_name,predicate,confidence,evidence_quote}],consequences:[{subject_name,decision_title,predicate,object,confidence,evidence_quote}],decisions:[{title,context,evidence_quote,options:[{title,rationale,selected,evidence_quote,delta:{base:'architecture',operations:[...]}}]}]}. For every option delta use exactly {base:'architecture',operations:[...]}. Each operation must use one supported shape: {op:'add_entity',entity:{id,kind,name,description?}}; {op:'remove_entity',entity:{id}}; {op:'replace_entity',entity:{id,kind,name,description?}}; {op:'add_relationship',relationship:{id,from,to,kind}}; {op:'remove_relationship',relationship:{id}}; {op:'replace_relationship',relationship:{id,from,to,kind}}. Any operation may also include the optional precondition expect:{} or expect:{exists:boolean}; do not include other expect fields or value types. Use only exact stable IDs present in the supplied passages or explicit operation data; never invent IDs or infer a graph change from a decision title. When a source-grounded typed operation and its required IDs cannot be formed safely, return operations:[] and preserve the decision/options. A consequence subject may be an entity name or decision_title matching an extracted decision. Relationship predicate should be a structural relation such as uses, publishes_to, calls, depends_on, stores_in, communicates_with, or implements. Consequences use a concise predicate and statement as object. Every evidence_quote must be an exact quote from one supplied passage and must uniquely identify it. Never invent an entity, relationship, consequence, or evidence; do not mark an option selected unless the source says it was selected."}, {"role": "user", "content": text}], response_format={"type": "json_object"}, api_base=litellm_api_base(connection), api_key=litellm_api_key(connection), timeout=litellm_request_timeout(connection), **litellm_generation_kwargs(connection))
        return parse_json_reply(result.choices[0].message.content)
    except Exception as exc:
        raise ProviderError(f"LiteLLM extraction failed: {type(exc).__name__}: {exc}") from exc


def propose_delta_with_litellm(connection: dict[str, Any], decision: dict[str, Any], option: dict[str, Any], request: str, graph: dict[str, Any]) -> dict[str, Any]:
    """Propose a typed option delta for preview; the caller persists only on explicit save."""
    try:
        import json
        import litellm
        result = litellm.completion(model=litellm_model(connection), messages=[
            {"role": "system", "content": "Edit architecture option deltas. Return JSON only with {delta:{base:'architecture',operations:[...]},rationale:'...',warnings:[...]}. Each operation must use one supported shape: {op:'add_entity',entity:{id,kind,name,description?}}; {op:'remove_entity',entity:{id}}; {op:'replace_entity',entity:{id,kind,name,description?}}; {op:'add_relationship',relationship:{id,from,to,kind}}; {op:'remove_relationship',relationship:{id}}; {op:'replace_relationship',relationship:{id,from,to,kind}}. Any operation may also include the optional precondition expect:{} or expect:{exists:boolean}. Every operation has an op field; include no fields beyond these shapes. Every change must follow the request; use stable IDs from the current option or deterministic slugs for new nodes. Do not claim a change is verified."},
            {"role": "user", "content": json.dumps({"decision": decision, "option": option, "request": request, "current_graph": graph}, ensure_ascii=False)},
        ], response_format={"type": "json_object"}, api_base=litellm_api_base(connection), api_key=litellm_api_key(connection), timeout=litellm_request_timeout(connection), **litellm_generation_kwargs(connection))
        return parse_json_reply(result.choices[0].message.content)
    except Exception as exc:
        raise ProviderError(f"LiteLLM delta proposal failed: {type(exc).__name__}: {exc}") from exc

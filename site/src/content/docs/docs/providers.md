---
title: Model providers
description: Configure a local OpenAI-compatible model server or a hosted provider for extraction and embeddings, and read the connection diagnostics.
---

Extraction works without any model: the deterministic/mock path is built in. A model connection adds provider extraction, delta proposals, and semantic embeddings. Connections are provider-neutral `model_connection` records in `.decision/connections/`. A LiteLLM adapter maps them to the provider internally.

## Local OpenAI-compatible server

Use `provider: openai_compatible` for any server that exposes an OpenAI-compatible `/v1` API. From inside the Compose backend, reach a server on your host through `host.docker.internal`:

```yaml
schema_version: decision/v1
record_type: model_connection
id: model-local-main
provider: openai_compatible
endpoint: http://host.docker.internal:1234/v1   # your server's port
model: local-model-id
embedding_model: local-embedding-model-id       # optional
capabilities:
  structured_output: true
  embeddings: true
  streaming: true
```

Local `openai_compatible` connections may omit `credential_ref`. The backend then sends a placeholder key, which a local server may ignore. If you set an explicit `env:` reference, it is used.

| Server | Status |
| --- | --- |
| Lemonade | Exercised: local Gemma generation and Nomic embeddings ran on disposable test fixtures. |
| Ollama, llama.cpp server, LM Studio | **Unverified.** Point `openai_compatible` at the server's OpenAI-compatible endpoint. The backend also accepts `ollama` and `lm_studio` provider names; no recorded check covers them. |

The Lemonade result is bounded: three repetitions of one explicit-choice fixture. It is not evidence of general extraction recall or repeatability.

## Hosted providers

`provider: openai` and `provider: anthropic` use the providers' own endpoints; any `endpoint` field is ignored. Credentials come from an environment variable:

```yaml
schema_version: decision/v1
record_type: model_connection
id: model-hosted
provider: anthropic
model: your-model-id
credential_ref: env:DECISION_MODEL_API_KEY
capabilities:
  structured_output: true
  streaming: true
```

:::caution[Unverified]
Hosted-provider interoperability has not been tested. No external credentials or hosted diagnostics were exercised.
:::

## Embeddings

Set `embedding_model` and `capabilities.embeddings: true` to use provider embeddings for both Qdrant indexing and queries. Without that, the backend uses deterministic token-hash vectors as an offline fallback and reports that mode. Those vectors are not semantic embeddings.

## Diagnostics

The connection diagnostics report each capability as supported, unsupported, or error, with raw and normalized errors:

- authentication
- endpoint reachability
- model availability
- structured output
- embeddings
- streaming
- latency

A reachable endpoint that returns HTTP 401 or 403 reports an authentication error while endpoint reachability stays supported. A capability without an implemented probe reports `capability_probe_not_implemented`, meaning unverified.

## How provider extraction behaves

- The prompt requests typed option deltas using the supported operations, and `operations: []` when no safe operation fits.
- Malformed operations get one retry with schema feedback. Records still invalid after that are not saved; their diagnostics appear in the completion summary.
- A safely anchored decision whose deltas still fail may be saved with empty deltas and an `extraction_review` audit, marked in the UI for manual repair.
- Repeated inferred decisions merge only on one unambiguous match of evidence, option labels, and selected label.
- After saving, the backend rebuilds SQLite and Qdrant from the canonical files.

## Secrets

Never commit secret values. `credential_ref` holds only an environment variable name such as `env:DECISION_MODEL_API_KEY`.

---
title: Portable format reference
description: The .decision/ folder layout and the decision/v1 YAML records for evidence, claims, entities, aliases, decisions, scenarios, and model connections.
---

`.decision/` is a small, human-readable overlay that lives in Git beside your source documents. It is canonical and readable without the app. Every YAML record validates against a versioned schema. Unsupported versions fail clearly; migrations must be explicit. Provider secrets never appear in these files.

## Layout

```text
.decision/
  config.yaml
  schema/
    record-v1.schema.json
  entities/<entity-id>.yaml
  evidence/<evidence-id>.yaml
  aliases/<alias-id>.yaml
  claims/<claim-id>.yaml
  relationships/<relationship-id>.yaml
  decisions/<decision-id>.yaml
  scenarios/<scenario-id>.yaml
  connections/<connection-id>.yaml
  agents/<agent-id>.yaml   # optional coding-agent references
  instructions.md
```

One record per file keeps diffs and merges focused. `config.yaml` selects the schema version, extraction and index preferences, and model connection IDs; it holds no credentials. `instructions.md` holds human extraction hints, not required syntax for your documents.

Every record declares `schema_version: decision/v1` and a `record_type`. The examples below are illustrative.

## Evidence

```yaml
schema_version: decision/v1
record_type: evidence
id: evidence-01j-example
source:
  path: docs/platform.md
  git_blob: null          # null when Git is unavailable
  content_sha256: "<64 lowercase hex>"
location:
  heading_path: [Messaging, Current platform]
  normalized_passage_sha256: "<64 lowercase hex>"
  context_before: "..."
  context_after: "..."
  display_line: 42        # hint only; never identity
text: Kafka supports replay.
```

The passage hash is SHA-256 of the case-folded, whitespace-collapsed `text`. The content hash is SHA-256 of the source file bytes. Every evidence ID cited elsewhere must resolve to exactly one evidence file.

## Claim

```yaml
schema_version: decision/v1
record_type: claim
id: claim-01j-example
subject: decision-messaging
predicate: motivated_by
object: event-replay-requirements
epistemic_state: inferred   # inferred | confirmed | rejected | asserted
confidence: 0.86
evidence:
  - evidence-01j-example
```

A consequence is a claim with predicate `consequence` and a descriptive object. Identity links use predicate `same_entity_as`.

### Human review and undo fields

Human review records add `reviewed_claim` (chain root), `reviewer`, `supersedes`, and an optional `reviewed_at` UTC timestamp. An undo record also names the reverted record in `undoes`. Readers drop every record named by `undoes`, and every undo record, before computing effective claims. Older readers that ignore `undoes` keep the undone judgment in effect.

## Entity and alias

```yaml
schema_version: decision/v1
record_type: entity
id: entity-kafka
kind: technology
name: Apache Kafka
description: Distributed event streaming platform
```

```yaml
schema_version: decision/v1
record_type: alias
id: alias-kafka-short
entity_id: entity-kafka
name: Kafka
epistemic_state: inferred
confidence: 0.97
evidence: [evidence-01j-example]
```

## Decision with options and deltas

```yaml
schema_version: decision/v1
record_type: decision
id: decision-messaging
title: Select the event transport
status: decided            # proposed | decided | superseded
context: Services need asynchronous event delivery.
evidence: [evidence-01j-example]
selected_option: option-kafka
options:
  - id: option-kafka
    title: Kafka
    rationale: Existing event ecosystem and replay requirements.
    evidence: [evidence-kafka-rationale]
    delta:
      base: architecture
      operations:
        - op: add_entity
          entity: {id: entity-kafka, kind: technology, name: Apache Kafka}
        - op: add_relationship
          relationship: {id: edge-events-kafka, from: service-orders, to: entity-kafka, kind: publishes_to}
  - id: option-sqs
    title: Amazon SQS
    rationale: Managed queue with less operational ownership.
    evidence: [evidence-sqs-rationale]
    delta:
      base: architecture
      operations:
        - op: add_entity
          entity: {id: entity-sqs, kind: technology, name: Amazon SQS}
        - op: add_relationship
          relationship: {id: edge-events-sqs, from: service-orders, to: entity-sqs, kind: publishes_to}
```

Selecting Kafka and SQS together is invalid: a decision permits one selected option.

### Extraction review metadata

When a model proposes an evidence-anchored decision whose option deltas fail validation, extraction may save the decision with empty active deltas and a top-level `extraction_review` object holding the rejected JSON and validator errors. The compiler never applies that metadata. A validated manual edit of an option clears that option's audit item.

## Scenario

```yaml
schema_version: decision/v1
record_type: scenario
id: scenario-managed-queue
name: Managed queue migration
selections:
  decision-messaging: option-sqs
  decision-storage: option-dynamodb
```

## Model connection

```yaml
schema_version: decision/v1
record_type: model_connection
id: model-local-main
provider: openai_compatible
endpoint: http://host.docker.internal:1234/v1
model: local-model-id
embedding_model: local-embedding-model-id   # optional
credential_ref: env:DECISION_MODEL_API_KEY  # optional for local openai_compatible
capabilities:
  structured_output: true
  embeddings: true
  streaming: true
```

`credential_ref` names an environment variable. The secret value is never written to YAML. See [Model providers](../providers/).

## Versioning

Only `decision/v1` exists. Unknown versions are rejected before any write. No v1-to-v2 migration exists; any incompatible shape change requires an explicit, deterministic migration that preserves IDs.

## Portability checks

- Copy `.decision/` and the Markdown into a fresh checkout; no index files are needed to compile.
- Delete generated SQLite and Qdrant data and rebuild from repository files.
- IDs and human states survive round-trip read/write and re-extraction.

## Write safety

Each YAML record is written through a same-directory temporary file, flushed, and atomically replaced. A process interruption leaves that record complete in its old or new version. This guarantee is per record: multi-record scans are not transactional, and concurrent writers are not serialized.

# Portable repository format

## Goals

`.decision/` is a small, human-readable Git overlay beside ordinary source documents. It is canonical and usable without this application. SQLite, Qdrant, embeddings, LangGraph checkpoints, generated graphs, and caches are rebuildable. Never commit provider secrets. All YAML validates against a versioned schema; unsupported versions fail clearly and migrations are explicit.

## Proposed layout

```text
.decision/
  config.yaml
  schema/
    record-v1.schema.json # versioned discriminated schema for all record types
  entities/<entity-id>.yaml
  evidence/<evidence-id>.yaml
  aliases/<alias-id>.yaml
  claims/<claim-id>.yaml
  relationships/<relationship-id>.yaml
  decisions/<decision-id>.yaml
  scenarios/<scenario-id>.yaml
  connections/<connection-id>.yaml
  agents/<agent-id>.yaml # optional external coding-agent connection references
  instructions.md
```

One record per file supports focused diffs and merges. Human-authored IDs should be stable opaque slugs/UUIDs rather than mutable display names. V0 inferred entity IDs are deterministic from case-folded names, and inferred alias IDs include the entity ID and alias name; renaming an extracted entity or alias can create a new ID. Evidence anchors use separate source/content/structure identity and can survive such renames when the same passage relocates unambiguously. `config.yaml` selects a schema version, extraction/index preferences, and model connection IDs by purpose; it excludes credentials. `instructions.md` contains human extraction hints, not required syntax for source documents.

## Evidence records and references

Evidence is canonical so multiple claims, aliases, decisions, options, and consequences can refer to one source anchor without copying it or relying on a dangling ID. Every evidence ID must resolve to exactly one `.decision/evidence/<id>.yaml` record. On relocation, retain that record's ID when the passage match is unambiguous. Claim status and evidence identity remain separate.

```yaml
schema_version: decision/v1
record_type: evidence
id: evidence-01j-example
source:
  path: docs/platform.md
  git_blob: null # null when Git is unavailable
  content_sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef" # 64 lowercase hex characters
location:
  heading_path: [Messaging, Current platform]
  normalized_passage_sha256: "aad82dbbea2e79c0e6fa9ed88aa1b880115754c6817b1e0867c87a65757ba502"
  context_before: "..."
  context_after: "..."
  display_line: 42 # hint only; never identity
text: Kafka supports replay.
```

The passage hash is SHA-256 of the case-folded, whitespace-collapsed `text`. The content hash is SHA-256 of the source file bytes; the example value above is a format placeholder.

## Common claim and evidence shape

Illustrative YAML (field names are normative for V0; examples are illustrative):

```yaml
schema_version: decision/v1
record_type: claim
id: claim-01j-example
subject: decision-messaging
predicate: motivated_by
object: event-replay-requirements
epistemic_state: inferred # inferred | confirmed | rejected | asserted
confidence: 0.86
evidence:
  - evidence-01j-example
```

Claim status belongs to each proposition. Rejection records remain durable and suppress the corresponding inference without deleting source text. `asserted` records a human override and may optionally reference the inference it supersedes. Human edits outrank model output during compilation.

### Identity-link claims (backend/API and frontend implemented)

Represent an identity link as an ordinary `decision/v1` claim whose predicate is `same_entity_as`. Both endpoints are IDs of existing base entity records, the entity kinds must match, and an entity cannot link to itself. The relation is symmetric; stored subject/object order does not imply a preferred or canonical ID. The schema file and v1 claim shape are unchanged; this adds predicate semantics, so no schema version change or migration is needed now. Any incompatible schema shape change requires an explicit versioned migration.

The backend validates the portable schema on every save and validates identity endpoints on save, read, review, and correction. Full cross-record validation runs on reads, not on generic saves, so incremental scan and extraction writes can proceed safely.

### Extraction delta review metadata

An inferred decision may carry an optional top-level `extraction_review` object when its evidence-anchored options and selection are valid but generated option deltas fail validation. The active option deltas are saved empty; the rejected JSON and validator errors are kept in the audit metadata and are never compiled as operations. The bundled v1 schema declares and validates this optional object. A successful manual option-delta edit removes that option's audit item; the field remains `status: required` while other items remain, and is removed after all listed options are edited and validated.

This additive metadata does not change the v1 schema version or rewrite a project's canonical schema copy. The backend validates `extraction_review` against the bundled v1 definition on normal record reads and writes, including when an existing repository has an older, permissive `.decision/schema/record-v1.schema.json`. That older schema copy does not independently validate the field; a deliberate schema refresh or migration is needed for standalone validators to enforce it. Older readers that ignore unknown fields can still read the decision, while writers that drop unknown fields can discard the review audit.

Use the existing epistemic states: `inferred` is a suggestion and never groups identities; `confirmed` or `asserted` is a human positive judgment; `rejected` rejects that pair. For example, an inferred suggestion uses the ordinary claim fields and retains its confidence and provenance:

```yaml
schema_version: decision/v1
record_type: claim
id: claim-identity-suggestion
subject: entity-kafka-extracted
predicate: same_entity_as
object: broker-kafka
epistemic_state: inferred
confidence: 0.91
evidence: [evidence-kafka-source]
```

The example is illustrative and does not assert that these IDs are identical. Exact-name matches between same-kind entities may produce suggestions only; name equality is not proof and must never resolve identity. Exact-name candidate matching normalizes case and whitespace. The pair review API writes a human claim with empty evidence and no source provenance, accepts confirmed, asserted, or rejected states, and an unconflicted rejected pair remains visible as a human judgment with review actions, while a pair already surfaced as a conflict appears only in its conflict card. Repeating the active judgment is idempotent and later judgments supersede prior pair judgments. Inferred claim reviews retain their available evidence and provenance. Human review appends claims and preserves the suggestion and review history. A review record points to the root with `reviewed_claim` and lists prior judgments in `supersedes`; a corrected asserted claim supersedes the reviewed chain. Alias records have their own review chains: confirming or rejecting an alias mapping does not judge entity identity, and identity review does not rewrite alias mappings.

Index identity claims by the unordered endpoint pair while retaining their stored endpoints. Only an active human confirmed/asserted link groups its endpoints; a rejection blocks that pair. Multiple unsuperseded conflicting human judgments surface as a conflict, never resolved by record order, confidence, or name. Confirmed links form read-time transitive groups; do not persist inferred transitive links. Positive cycles are harmless. If a rejected pair is connected through confirmed links, surface a conflict and do not treat that connected component as one identity group until the conflict is resolved.

Graph, search, and entity-detail API responses expose read-time identity groups, suggestions, and conflicts. Search uses full claim history to report identity review state and conflicts; scenario graph compilation continues to use effective claims. The frontend shows groups, suggestions, conflicts, exact-name pair actions, and claim-backed inferred review in entity details and Facts. Preserve and expose each stable entity ID and its provenance. The map may render a human-confirmed/asserted group as one logical node, using an existing member ID only as the rendered representative; this view projection does not change records or operations. Aggregate aliases and evidence in the selected component detail. Do not merge by display name, rewrite entity references, or collapse inferred/exact-name candidates. Validate and apply typed option deltas against original IDs; saved scenario selections and behavior remain unchanged. Option-created entities absent from the resolved scenario are not restored by identity projection.

### Human review log and undo

New human claim, alias, and identity review records carry an optional `reviewed_at` UTC ISO-8601 timestamp. `GET /api/v1/reviews` lists human review records newest first; legacy records without `reviewed_at` follow timestamped records and are ordered by supersession depth.

`POST /api/v1/reviews/{record_id}/undo` appends an undo record to the same folder as the judgment it reverts. The undo record copies the undone record's proposition, keeps the chain's `reviewed_claim` or `reviewed_alias` root (the undone record itself when it has none), lists the undone ID in `supersedes`, and names it in the optional `undoes` field:

```yaml
schema_version: decision/v1
record_type: claim
id: human-undo-0123456789abcdef
subject: service-orders
predicate: uses
object: entity-kafka
epistemic_state: confirmed # copied from the undone judgment; not an effective judgment
confidence: 0.8
evidence: [evidence-01j-example]
reviewed_claim: claim-01j-example
reviewer: human
reviewed_at: "2026-10-15T12:00:00.000000+00:00"
supersedes: [human-claim-undone]
undoes: human-claim-undone
```

Readers drop every record named by an `undoes` field and every undo record before computing effective claims, aliases, identity groups, suggestions, and conflicts. The undone record's `supersedes` list therefore no longer applies: the prior human judgment, or the original inference when none exists, becomes effective again. No file is deleted or rewritten. Only the unsuperseded head of a review chain is undoable; an undo record cannot itself be undone, and redo is a new review that supersedes the undone record and its undo. Repeating an undo returns the existing record, whose ID derives from the undone ID.

`reviewed_at` and `undoes` are additive optional v1 fields declared in the bundled schema and validated against it on reads and writes, as with `extraction_review`; an existing project's schema copy is not rewritten. Reads also require an undo record to supersede an existing record in its folder. Older readers that ignore `undoes` do not honor undo: they treat the undo record as a copy of the undone judgment, so that judgment stays in effect for them.

`source_kind` is not a normative v1 claim field and the V0 runtime assigns it no meaning. A future code-analysis source/type needs an explicit schema and API design before clients can rely on it.

## Entity and alias records

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

Alias mappings are independently evidenced and confirmed/rejected/overridden. Do not treat aliases as unreviewable strings attached to an entity.

Every extraction-created decision, option rationale, relationship, or consequence also cites evidence IDs. Evidence is required for inferred propositions. Human-authored statements may omit it when they are explicit assertions rather than source-derived claims.

## Provider configuration

The public model connection contract is provider-neutral and contains no credentials. `provider` selects an adapter name; hosted OpenAI and Anthropic use their provider endpoints, while `endpoint` configures compatible/local providers; `model` names the inference model. An optional `embedding_model` names a distinct vector model when `capabilities.embeddings` is enabled. Diagnostics probe embeddings only when that model is supplied, otherwise they report embeddings as unsupported. Credential references resolve from runtime environment/secret storage and never inline secret material.

```yaml
schema_version: decision/v1
record_type: model_connection
id: model-local-main
provider: openai_compatible
endpoint: http://host.docker.internal:1234/v1 # host model server from the Compose backend
model: local-model-id
embedding_model: local-embedding-model-id # optional; required to probe/use provider embeddings
credential_ref: env:DECISION_MODEL_API_KEY
capabilities:
  structured_output: true
  embeddings: true
  streaming: true
generation: # optional
  reasoning: "off" # off | low | medium | high
  max_output_tokens: 4096
  request_timeout_seconds: 1800 # optional; default 600
```

The optional additive `generation` object holds per-request generation controls and is valid only on `model_connection` records. `reasoning` sets how much hidden reasoning a reasoning-capable model may spend before answering; `off` disables it. Quote `"off"` in YAML so it stays a string. `max_output_tokens` is a positive integer cap on generated tokens, reasoning included. `request_timeout_seconds` is a positive number of seconds, at most 86400, that one extraction or delta-proposal completion may take; without it the adapter uses 600. All fields are optional; blank fields are omitted on save. Re-saving a connection without `generation` (or with `null`) keeps the stored value, so clients that do not edit it cannot erase it; an explicit empty object `{}` clears it. Unknown keys and other values are rejected. The backend validates `generation` against the bundled v1 schema on every read and write, including projects whose overlay schema copy predates the field. Readers that ignore `generation` are unaffected, but the `generation` definition is closed (`additionalProperties: false`): a backend or standalone validator using a schema from before `request_timeout_seconds` existed rejects a connection record that declares it. Omit the field when older backends or validators must read the record.

The LiteLLM adapter maps `reasoning` to `reasoning_effort` (`off` becomes `none`, other levels pass through) `max_output_tokens` to `max_tokens`, and `request_timeout_seconds` to the completion `timeout`. LiteLLM forwards `reasoning_effort: none` unchanged to `openai_compatible` and `lm_studio` endpoints; llama.cpp-based servers such as Lemonade then disable the chat template's thinking mode. For `ollama`, LiteLLM converts it to `think: false`. For `anthropic`, `off` sends no parameter because extended thinking is off unless requested. Hosted `openai` models that reject `reasoning_effort` fail with a provider error; omit `reasoning` for them. Some hosted reasoning models may also reject `off` (`none`), for example models that accept only `minimal` as their lowest level. Hosted-provider behavior is unverified.

An optional `agents/` record references an external coding/engineering agent and its invocation configuration; it is distinct from `model_connection` and does not declare inference capabilities. Agent integration details and transport remain unresolved. LiteLLM is an internal adapter, not the portable schema. If no provider embedding model is configured, V0 uses deterministic local token-hash vectors; that fallback is rebuildable but is not semantic embedding retrieval. Embedding failures are reported in scan/search diagnostics and do not silently switch a configured provider-backed index to a different vectorizer.

## Decision evidence and consequences

Option rationale cites canonical evidence records through its `evidence` field. V1 does not define a nested `consequences` object. Represent an inferred consequence as a claim with the decision or entity as its subject, `consequence` as its predicate, a descriptive value as its object, and the supporting evidence:

```yaml
schema_version: decision/v1
record_type: claim
id: claim-kafka-replay-consequence
subject: decision-messaging
predicate: consequence
object: Event replay remains available for downstream recovery.
epistemic_state: inferred
confidence: 0.82
evidence: [evidence-kafka-rationale]
```

The `evidence-kafka-rationale` and `evidence-sqs-rationale` IDs in the option example are separate files under `.decision/evidence/`, each using the canonical evidence record shape above.

## Decision, option, and delta records

```yaml
schema_version: decision/v1
record_type: decision
id: decision-messaging
title: Select the event transport
status: decided # proposed | decided | superseded
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

V0 operations add, remove, or replace entities and relationships. Each operation has a compiler-validated shape and stable target ID. Operations may carry an optional `expect` precondition: `{}` is accepted, or `{"exists": true|false}` checks whether the target exists at that point in composition. Other keys or non-boolean `exists` values are invalid. Deltas describe changes relative to the shared base, not full copied snapshots. V1 requires `kind` strings but does not constrain entity kinds or relationship kinds to a closed vocabulary. It types claim predicates as strings; the compiler recognizes a code-defined set of structural predicates.

For this example, the `architecture` base is compiled from effective portable entities and relationships after rejected claims are excluded and human precedence is applied. It contains `service-orders` and has no selected event transport. Each option independently adds its own technology and `publishes_to` relationship. Applying Kafka and SQS as competing selections together is invalid because the decision permits one selected option. A removal must identify its target; an optional `expect` precondition can state whether that target must exist in the base or an earlier composed operation.

The compiler's code-defined structural predicate set contributes graph nodes and edges to the base. Context, motivation, consequence, rationale, and other descriptive claims remain attached to decision/evidence records and do not imply that an option's components are already present.

## Scenarios

```yaml
schema_version: decision/v1
record_type: scenario
id: scenario-managed-queue
name: Managed queue migration
selections:
  decision-messaging: option-sqs
  decision-storage: option-dynamodb
```

Scenario application composes selected option operations over one base graph. Compilation reports invalid references, conflicting operations, affected decisions, invalid assumptions, and evidence links. Ordering and conflict resolution must be deterministic and surfaced, never silently guessed.

Read results carry a `receipt`: a SHA-256 digest over canonical JSON of the `.decision/` aliases, claims, decisions, entities, evidence, and relationships records, the unsuperseded human review heads, the evidence anchor hashes, and the resolved selections. It is derived, never stored, and depends only on these files, so copying `.decision/` into a fresh checkout reproduces it. See `docs/DEVELOPMENT.md` "Scenario diff, impact, and receipts".

## Identity, relocation, and migration

Evidence IDs survive edits when the indexing process unambiguously relocates the same passage. Relocation compares passages within the same repository-relative source path, first by normalized passage hash, then by heading path and surrounding context. The source record also stores Git blob and file-content hashes when available, but the current relocation matcher does not use those values. Reordering or line shifts alone do not create new evidence. Ambiguous relocation creates a reviewable unresolved anchor rather than silently attaching evidence to a different passage. Display lines are optional conveniences.

Each record declares `schema_version` and `record_type`. `.decision/schema/record-v1.schema.json` validates the shared envelope and supported record shapes, including typed operation payloads. The V0 runtime validates the schema on every save and validates identity endpoints on save/read/review/correction. Full cross-record validation runs on reads, not generic saves; other fields are validated at the operations that consume them. Although the v1 JSON Schema permits additional top-level fields, the runtime ignores fields it does not define or consume; in particular, decision `context_evidence` and `claims` are not supported v1 relations. No v1-to-v2 migration exists. Identity-link semantics fit the unchanged v1 claim shape and require no version change or migration now; an incompatible schema shape change requires an explicit deterministic migration that preserves IDs and produces reviewable diffs. Never silently rewrite unknown/future versions. Application import validates portable records against the schema; this checkout has no CI configuration.

## Portability checks

- Copy `.decision/` and Markdown into a fresh checkout; no local index files are required to compile.
- Delete generated SQLite/Qdrant data and rebuild indexes from repository content and portable records.
- Parse and validate all YAML with the matching schema version.
- Preserve IDs and human states through round-trip read/write and re-extraction.
- Keep state required to understand decisions, options, aliases, claims, evidence, and scenarios in committed text files.

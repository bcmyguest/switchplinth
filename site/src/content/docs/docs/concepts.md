---
title: Concepts
description: Decisions, options, typed deltas, scenarios, claims, evidence anchors, and how machine inference differs from human review.
---

The central object is a **decision**: a choice with context, options, and consequences. ADRs, RFCs, design docs, proposals, READMEs, and other Markdown are input artifacts. A team does not need an ADR convention.

## Source artifact

Repository content from which evidence is anchored. Today that means Markdown only. Source Markdown remains untouched input.

## Entity

An architecture concept such as a service, technology, datastore, or interface. Entity kinds are strings; v1 does not restrict them to a closed vocabulary.

## Decision

The selected-or-undecided choice with its rationale and context. A decision has a `status` (`proposed`, `decided`, or `superseded`), cites evidence, and names at most one `selected_option`.

## Option

A candidate response to a decision. An option carries a title, a rationale, evidence, and a **delta**. It is never a copied snapshot of the architecture.

## Typed delta

A list of typed operations against one shared base graph. v1 operations add, remove, or replace entities and relationships. Each operation has a compiler-validated shape and a stable target ID. An operation may carry an `expect` precondition: `{}` or `{exists: true|false}`.

```yaml
delta:
  base: architecture
  operations:
    - op: add_entity
      entity: {id: entity-sqs, kind: technology, name: Amazon SQS}
    - op: add_relationship
      relationship: {id: edge-events-sqs, from: service-orders, to: entity-sqs, kind: publishes_to}
```

YAML edits, graph edits in the UI, and model proposals all use this same delta shape.

## Scenario

A composition of selected options across decisions. The compiler applies the selected options in a stable order to the common base graph and reports changed entities and edges, affected decisions, invalid assumptions, conflicts, and supporting evidence. Ordering and conflict resolution are deterministic and surfaced, never guessed.

In the app, the Architecture map's **What-if** panel treats option switches as a temporary preview with a one-click return to the repository's selected choices. Saving a named scenario writes its selections to `.decision/scenarios/`. Scenarios support create, list, and load; rename, update, and delete are not implemented.

## Claim

A proposition about an entity, alias, relationship, decision, or consequence. Each claim has a subject, a predicate, an object, an epistemic state, a confidence, and evidence.

**Alias claims** state that a name refers to an entity. They are reviewed separately from claims about the entity itself.

**Identity links** use the predicate `same_entity_as` between two distinct entities of the same kind. Only a human-confirmed or asserted link groups entities. Exact-name matches and inferred links stay suggestions. The map may draw a human-confirmed group as one logical node without rewriting any stored ID.

## Evidence anchor

A stable locator and content identity for a source passage. An anchor combines:

- the repository-relative source path,
- Git blob and file-content hashes where available,
- the heading path,
- a normalized passage hash,
- surrounding context before and after.

Line numbers are display hints only. When a passage moves, the indexer relocates the anchor by passage hash, then by heading path and context, within the same source path. An ambiguous match becomes a reviewable unresolved anchor instead of silently attaching to a different passage.

## Inference versus human review

| State       | Meaning                                                        |
| ----------- | -------------------------------------------------------------- |
| `inferred`  | Machine-proposed interpretation. Carries evidence and confidence. |
| `confirmed` | A human accepted the proposition.                              |
| `rejected`  | A human rejected it. The record stays and suppresses the inference. |
| `asserted`  | A human override, optionally superseding an inference.         |

Human review appends records; it never mutates the original inference into an indistinguishable fact. A review record points to the chain root with `reviewed_claim` (or `reviewed_alias`) and lists prior judgments in `supersedes`. During compilation, human judgments outrank model output, and re-extraction leaves human-reviewed records byte-for-byte unchanged.

Undo appends a record whose `undoes` field reverts the head of one review chain, restoring the prior judgment or the original inference. No file is deleted or rewritten. The Facts page shows this review log, with the prior state and an Undo action on each entry; the API exposes the same operations (`GET /api/v1/reviews`, `POST /api/v1/reviews/{record_id}/undo`).

## Grounded answers

For "why" questions, such as "Why are we using Kafka?", search returns `grounded: true` only when effective claims cite the returned passages. When passages exist without claim support, the answer returns the passages and is labeled not fully grounded.

## Canonical versus disposable

Markdown and validated `.decision/` YAML are canonical. SQLite, Qdrant vectors, and graph projections are disposable and rebuild from those files.

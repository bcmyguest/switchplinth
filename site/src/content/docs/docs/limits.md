---
title: What works today
description: What the local build verifiably does, and the known limits - untested hosted providers, unmeasured extraction recall, mock-extracted sample, loopback-only API.
---

This page separates recorded, verified behavior from open limits. If a feature is not on this page or in the docs, assume it does not exist.

## Verified locally

- `docker compose up --build` starts separate frontend, backend, and Qdrant services, with ports bound to loopback.
- A repository of non-template Markdown opens, bootstraps `.decision/`, and runs discovery.
- The mock path and an OpenAI-compatible provider path produce portable records with evidence.
- Human confirm, reject, and correct survive re-extraction and outrank inference.
- Selecting options recomputes the scenario graph; the map's What-if panel switches options in place.
- A grounded "why" query returns supporting claims and inspectable passages.
- Deleting SQLite and Qdrant state and rebuilding from canonical files restores usable indexes.
- Schema validation rejects unsupported versions before writing.
- MCP initialize, tools list, and query passed over streamable HTTP.
- `./scripts/demo.sh` bootstraps the food-delivery sample and starts the stack with one command.
- Local Lemonade runs with Gemma generation and Nomic embeddings passed a bounded gate: three repetitions of one explicit-choice fixture.

## Known limits

1. **Hosted providers are untested.** OpenAI and Anthropic adapters exist; no external credentials or hosted diagnostics were exercised.
2. **Extraction recall is unmeasured.** Claim-level repeatability is unverified. Re-extraction on the local fixture added one or two inferred claims per run with varied wording.
3. **The food-delivery sample uses deterministic mock extraction** whose rules are tuned to that sample's text. It demonstrates the decision and what-if model, not extraction quality on arbitrary ADRs.
4. **Local-model extraction on the food-delivery sample has not completed.** An earlier attempt with a previous model timed out; that result is inconclusive.
5. **The API and MCP are unauthenticated and loopback-only.** No remote-access or authentication design exists. Do not expose them.
6. **Markdown only.** No code parsing, PDFs, or other formats.
7. **Without an embedding model, vector search uses token-hash vectors**, not semantic embeddings.
8. **Writes are atomic per YAML record only.** Multi-record scans are not transactional, and concurrent writers are not serialized.
9. **Schema v1 only.** No migration path exists yet.
10. **Scenario rename, update, and delete are not implemented.**
11. **Review undo has no UI yet.** It works through the API.
12. **Conflict detection is narrow.** The compiler reports a conflict only when two selected options write the same entity or relationship ID.
13. **Single local user.** No hosted or multi-user mode.
14. **The UI is in progress.** The map now uses an automatic layered layout with orthogonal edges and has a fullscreen mode; fixes from the fullscreen review are still in progress.

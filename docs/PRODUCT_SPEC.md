# Product specification

## Intent

Help a team understand and evolve the architecture expressed across its existing repository documents. The product discovers likely decisions, options, architecture entities, aliases, relationships, evidence, and consequences from heterogeneous Markdown. It makes the evidence and uncertainty inspectable, supports human correction, and lets users explore coherent what-if scenarios.

The central domain concept is a **Decision**: a choice with context, options, and consequences. ADRs, RFCs, design docs, proposals, READMEs, tickets, and arbitrary Markdown are input artifacts. Teams do not need an ADR convention to get value.

The product is **Switchplinth**, formerly the working title **Decision Graph** and the provisional UI label **Waypoint**. The UI, Python package, CLI, MCP server name, and Compose project use the new name.

## Users and primary flow

1. Open a local repository.
2. Select a configured AI provider or use deterministic/mock extraction.
3. Discover likely decision-bearing Markdown artifacts and extract candidate decisions, options, entities, aliases, relationships, evidence, and consequences.
4. Review “what we think your architecture is.” Inspect evidence and confirm, reject, or correct uncertain claims and alias mappings.
5. Browse the resulting graph. Select an entity to see rationale from an active linked option, any linked unselected option marked as an alternative, related decisions, and source evidence.
6. Select different decision options to compose a scenario. The graph and affected decisions, conflicts, invalid assumptions, and evidence update promptly.
7. Ask a grounded question such as “Why are we using Kafka?” and inspect the supporting passages and claims.
8. Edit the same domain model in the UI, via portable YAML, or through conversational assistance. Re-extraction preserves human decisions.

## Terms

- **Source artifact:** repository content, initially Markdown, from which evidence is anchored.
- **Entity:** an architecture concept such as a service, technology, datastore, or interface.
- **Claim:** a proposition about an entity, alias, relationship, decision, or consequence, with epistemic state and provenance as applicable.
- **Alias claim:** a separately reviewable claim that a name refers to an entity.
- **Decision:** the selected-or-undecided choice and its rationale/context.
- **Option:** a candidate response to a decision, represented by typed operations against a base graph.
- **Scenario:** a composition of selected options across decisions.
- **Evidence anchor:** a stable locator and content identity for a source passage.
- **Inference:** a machine-proposed interpretation, never an unchangeable fact.

## Scope for V0

- Local repository opening and recursive Markdown discovery with generated/build directories excluded by documented defaults and user-configurable ignore rules.
- Deterministic/mock extraction plus at least one real provider path behind a provider-neutral configuration contract.
- Portable overlay creation and schema validation; stable evidence identity and relocation after source edits.
- Human confirmation, rejection, and override for claims and aliases; human-authored records outrank model inference.
- **Backend/API and frontend presentation implemented:** portable identity links use `same_entity_as` claims between distinct entities of the same kind. Only a human-confirmed/asserted link groups identities; inferred exact-name matches are suggestions only. Review history and conflicts remain available through the backend, and identity review stays separate from alias review.
- Graph, search, and entity-detail API reads expose identity groups, suggestions, and conflicts while preserving stable entity IDs, claims, aliases, typed deltas, and saved scenario selections. The UI presents identity groups, suggestions, conflicts, and review actions; exact-name candidates use the pair review API while inferred claim suggestions retain the existing claim review APIs. Do not choose a representative ID or automatically collapse map nodes.
- Decision → option → typed delta, and composition of multiple selected options into a scenario.
- Interactive graph browsing/editing, evidence inspection, scenario switching, grounded lexical/semantic/entity/graph retrieval, and MCP query interface.
- Rebuild SQLite and Qdrant entirely from canonical repository files.
- Provider setup and diagnostic UI for authentication, endpoint reachability, model availability, structured output, embeddings, streaming, latency, and useful raw/normalized errors.
- Docker Compose local runtime with frontend, backend, and Qdrant separate.

## Out of scope

- Requiring or managing a proprietary ADR template.
- Code parsing, Tree-sitter/codegraph indexing, and implementation-versus-design conformance analysis. V1 has no normative `source_kind` field or code-evidence API; future code-derived evidence needs an explicit schema/API design and distinct provenance type.
- A hosted multi-tenant service, required cloud account, or canonical remote database.
- Postgres, Redis, Neo4j, or making SQLite/Qdrant canonical.
- Marketing site work in the application V0. Reusable visual/theme primitives may be retained; a future static React/Tailwind/shadcn marketing/docs site and synthetic scenario demo are separate work.

## Acceptance criteria

V0 is accepted when:

1. `docker compose up --build` starts distinct frontend, backend, and Qdrant services locally.
2. A repository with synthetic, non-template-specific Markdown can be opened and discovered without ADR-specific formatting.
3. A mock path and at least one configured provider path produce candidate portable overlay data.
4. Every inferred architectural claim has provenance. Evidence anchors use repository-relative identity, Git/content identity where available, structural location, normalized passage fingerprint, and context sufficient for relocation; re-indexing reuses anchor identity when passage relocation succeeds.
5. Alias mappings have independent confidence, evidence, and epistemic status.
6. Human confirmed/rejected/overridden records survive extraction and outrank inference.
   - V0 identity-link backend/API: portable `same_entity_as` claims validate two existing, distinct, same-kind entity endpoints; link direction is symmetric. Only active human confirmed/asserted links group identities. Rejections block that pair; conflicting human judgments and a rejected pair connected by a confirmed transitive path surface as conflicts. Exact-name, same-kind matches are suggestions only. Graph, search, and entity-detail API reads expose groups/conflicts without rewriting IDs/references. Frontend review exposes the link state and review actions in selected details and Facts, including rejected human judgments; alias review remains independent.
7. Decisions and options are represented using typed deltas over a base graph; selecting/composing options recomputes scenario graph effects.
8. The UI supports graph browsing, evidence inspection, entity-linked rationale and alternatives, and scenario option switching. Detail, What-if, and graph editing panels overlay the map while leaving the canvas position and width unchanged; mobile panels use a near-full-width drawer.
   - The map remains the primary working surface. Each overlay keeps a clear title, close action, and enough context to return to the selected node or decision.
   - The first-use map, scenario playground, and Facts queue each make the next useful action obvious without requiring the user to understand portable YAML first.
   - Facts supports triage of long review queues by separating direct candidates, rejected judgments, and conflicts; evidence and source passages remain easier to scan than internal IDs and confidence metadata.
9. A grounded “why are we using X?” query returns claims and passages that support the answer and can be inspected.
10. Deleting generated SQLite/Qdrant state and rebuilding from canonical files restores usable indexes without losing meaningful knowledge.
11. Versioned schema validation rejects unsupported versions before mutation; portability, precedence, delta application, and anchor relocation are covered by automated checks. Any future schema evolution must add and test an explicit deterministic migration.
12. Provider diagnostics report every capability as supported, unsupported, or error, including actionable raw and normalized failures; unsupported checks are visible rather than silently skipped.

## Unresolved choices

Local V0 decisions are settled: Markdown discovery excludes `.decision/`, `.decision-cache/`, `.tasks/`, `.pytest_cache/`, and standard build/cache directories by default, with configured path exclusions and source-specific includes; saved scenarios persist selections under `.decision/scenarios/`; MCP uses streamable HTTP; the unauthenticated API and MCP listeners bind to loopback; identity links connect same-kind entities, and identity groups do not automatically collapse visually. Any remote-access boundary remains unresolved, and external access stays disabled until it is defined.

- Which repositories/remotes and path-selection UX are supported at first launch (local filesystem repository is the V0 baseline).
- Whether provider credentials are held only in environment/runtime secrets or can be stored locally encrypted; never write secrets into portable YAML.
- Maximum Markdown file size and whether PDFs or other formats are added after V0.
- Authentication and exposure rules for any remote API or MCP access.
- Initial delta operation vocabulary beyond add/remove/replace entity or relationship; operation preconditions and conflict policy need implementation-time validation.
- Exact thresholds and interaction for scenario recomputation latency and alias suggestions. Identity suggestions use exact-name, same-kind matching as specified above.
- Which real provider receives first-class acceptance coverage; configuration remains provider-neutral.

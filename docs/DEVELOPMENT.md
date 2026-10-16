# Development notes

Setup, behavior, and verification detail for contributors and coding agents. The README covers the short version. Engineering rules are in [AGENTS.md](../AGENTS.md); the portable file format is in [PORTABLE_FORMAT.md](PORTABLE_FORMAT.md); the architecture is in [ARCHITECTURE.md](ARCHITECTURE.md).

## Names

Earlier revisions used “Decision Graph” as a working title and “Waypoint” as a provisional UI label. The product, Python package and import (`switchplinth`), CLI (`switchplinth`), MCP server name (`io.github.bcmyguest/switchplinth`), and Compose project (`switchplinth`) now use the name Switchplinth. The `DECISION_*` environment variables keep their names. The portable format keeps its `.decision/` directory and `decision/v1` schema version.

Switchplinth turns repository Markdown into a portable, reviewable architecture graph. It discovers ADRs, RFCs, design notes, and other Markdown without requiring a particular template. The source documents and validated YAML under `.decision/` are canonical; SQLite and Qdrant are disposable indexes.

## Status detail

Works today:

- Markdown discovery with no required template; the first open bootstraps `.decision/`.
- Deterministic mock extraction, and provider extraction through a local OpenAI-compatible server (verified on small fixtures).
- The system map, decision options, and What-if previews.
- Source evidence behind every inferred claim.
- Claim, alias, and identity review, with an append-only review log and undo on the Facts page.
- The Architecture log: rationale, each alternative's rejection reason where the source states one, and consequences.
- Saved scenarios: create, list, and load.
- Grounded search, and the MCP server over HTTP and stdio.
- SQLite and Qdrant indexes that rebuild from the canonical files.

Up next:

- Test hosted providers (OpenAI, Anthropic). The adapters exist; no hosted credentials have been exercised.
- Measure extraction recall on more repositories. Local model extraction has run only on small fixtures, and recall is unmeasured.
- Extraction beyond the fixture-tuned mock. The sample's mock extractor uses phrase rules written for the food-delivery text, so the sample shows the decision, option, and scenario model, not extraction quality. One local-model run on the sample found the same seven decisions and selected options as the mock, with a different component graph; one run is not a quality measure.
- Authentication for remote API and MCP access. Both are unauthenticated today and bind to loopback only.
- Source formats beyond Markdown. Markdown is the only format read today.
- Conflict detection beyond same-ID writes. Between selected options, the compiler checks only whether two decisions write the same entity or relationship ID.
- Scenario rename, update, and delete.

## Demo script

Requires Docker with Compose v2 and curl. No model, credentials, Python, or Node.

```sh
./scripts/demo.sh
```

The script builds the images, copies the fictional food-delivery sample (`fixtures/food-delivery/`) into `~/.cache/switchplinth-demo/food-delivery`, extracts it with fixture-tuned deterministic mock extraction, starts the stack as Compose project `switchplinth-demo`, rebuilds the search indexes, and prints the URL (<http://localhost:3000>). The sample yields 7 decisions and 18 components. `./scripts/demo.sh --down` stops the stack and deletes its volumes; `--reset` re-creates the sample; `--purge` stops the stack, deletes its volumes, and deletes the demo workspace. The backend container runs as root, so once you scan or review in the UI the workspace holds root-owned files; remove it with `--purge`, not `rm`. Set `DECISION_DEMO_WORKSPACE` to choose another directory, and `DECISION_FRONTEND_PORT`, `DECISION_BACKEND_PORT`, or `DECISION_QDRANT_PORT` if 3000, 8000, or 6333 is taken. Stop any other stack on those ports first. The sidebar shows the repository name `food-delivery`.

Earlier revisions named the demo stack `decision-graph-demo` and its workspace `~/.cache/decision-graph-demo`; the current script no longer touches either. Remove them with `COMPOSE_PROJECT_NAME=decision-graph-demo DECISION_DEMO_WORKSPACE=~/.cache/decision-graph-demo ./scripts/demo.sh --purge`.

## Local model connection

Optional: connect a local OpenAI-compatible model server (for example one listening on host port 1234) to try provider extraction:

```sh
curl -X POST "http://localhost:${DECISION_BACKEND_PORT:-8000}/api/v1/connections" -H 'Content-Type: application/json' \
  -d '{"id":"local-model","provider":"openai_compatible","endpoint":"http://host.docker.internal:1234/v1","model":"<your-model-id>","capabilities":{"structured_output":true}}'
```

Then choose **Discover decisions** and select that connection. The connection is saved under the sample's `.decision/`; it needs no API key.

The full connection reference is on the site's [model providers](https://bcmyguest.github.io/switchplinth/docs/providers/) page.

## Run with Docker Compose

Docker Compose starts three services:

```sh
docker compose up --build
```

- Web app: <http://localhost:3000>
- Backend API and OpenAPI docs: <http://localhost:8000/docs>
- Qdrant: <http://localhost:6333>

Published ports bind to `127.0.0.1` by default. The backend container maps `host.docker.internal` to the host gateway so local model servers can be reached from Linux Compose. The API is unauthenticated in V0; external listener access is not configured.

Compose mounts `${DECISION_WORKSPACE_HOST:-.}` at `/workspace/repos` (the current directory by default). The repository chooser lists Markdown repositories under that mounted directory; selected paths are relative, and paths that traverse symlinks or escape the mount are rejected. New Markdown-only repositories receive a portable `.decision/` v1 schema, config, and instructions on first open. To mount a different workspace, set `DECISION_WORKSPACE_HOST` before starting Compose. The container sees the mounted directory as `repos`; set `DECISION_WORKSPACE_NAME` to show its real name in the UI (`scripts/demo.sh` sets it to `food-delivery`).

## Workspace UI

The workspace navigation provides separate **Architecture**, **Architecture log**, **Progress**, and **Facts** pages. Architecture places the Decision assistant near the top of the system map flow. Architecture log lists decisions and links to scenario options; each decision shows its rationale, each alternative's "why not chosen" reason where the source states one, and consequences where present, with passage links, and a previewed What-if alternative is labelled as previewed, not rejected; Progress reports counts from the current graph and Markdown evidence; Facts contains **Needs a closer look** review controls and links back to the system map. Scenarios and Explore retain scenario selection and grounded assistant workflows. The theme control switches between light and dark semantic themes and remembers the choice in the browser. All **Discover** actions (Source Types, the page heading, and the source card) open the same mode choice: deterministic/mock extraction or a configured model connection. Provider mode sends that connection ID to `POST /api/v1/extraction/run`; its result names the provider/model and reports saved record counts or a visible error. After provider records are saved, SQLite and Qdrant are rebuilt from the canonical Markdown and `.decision/` data so search sees the new records. The sidebar’s **Source Types** control opens V0 Markdown source details and the shared Discover action. The UI can inspect inferred entities and evidence, review claims and aliases, switch decision options, edit their shared typed deltas, and resolve a scenario. On the Architecture map, the What-if overlay lets users switch decision options in place; the graph, rationale/evidence, and conflict/assumption state update without navigating to Scenarios. Selecting a map node opens component details beside the map without changing page scroll. The details show rationale and evidence from an option that changes that entity, label unselected option rationale as an alternative, and label other passages as source context. Review controls remain available on human-reviewed rows so judgments can be confirmed, rejected, or corrected again; new records supersede earlier judgments and preserve evidence. Claims may reference entities introduced by option deltas; projection includes those relationships only while both endpoints exist in the selected scenario. Saving a scenario writes its decision selections to `.decision/scenarios/`. A configured model can propose a delta for preview; manual delta edits can also use `POST /api/v1/scenarios/preview-delta` for server validation and scenario resolution without writing `.decision/`. Malformed operations return HTTP 422 before writing canonical files. Accepting the proposal updates the same option delta used by manual editing. Search accepts the current `selections` map so rationale and evidence follow the visible scenario. Without a configured model, proposal returns an unsupported response. Search returns answers only when supporting evidence is available.

## Discovery and scan

The repository chooser filters hidden/generated directories and only lists candidates containing Markdown, `.git`, or `.decision`. The discovery scan excludes `.decision/`, `.decision-cache/`, `.tasks/`, `.pytest_cache/`, and common build/cache directories by default. Add path segments under `extraction.ignore` in `.decision/config.yaml` to exclude more paths. To index task Markdown intentionally, add a source path or directory such as `extraction.include: [.tasks]`; this opts in only that source and does not override other ignored directories. When `.tasks/` is excluded, a scan marks prior evidence unresolved for historical provenance, filters excluded IDs from mixed-support inferred claims, decisions, options, entities, aliases, and evidence-bearing relationships, and removes safe task-only inferred content, including entirely task-grounded inferred decisions when they are unselected and unreferenced. Current-source inferred references can continue supporting a shared entity after task evidence is removed. Human-reviewed records and their review chains stay byte-for-byte unchanged. The scan fails closed when removing a selected or saved-scenario-referenced option, or when a task-only inferred entity or relationship remains referenced, including relationships referenced by active selected options or human-reviewed decision deltas. `extraction.max_candidates` limits inferred decision and candidate-passage output (default 50). `POST /api/v1/discovery/scan` performs discovery, extraction, and a full SQLite/Qdrant index rebuild; SQLite stores its index version, and Qdrant collections are namespaced by canonical repository path. If a synchronous scan operation raises, the backend restores the previous `.decision/` files. Abrupt process or host termination is outside that rollback guarantee.

## Identity links

Identity links use the existing `decision/v1` claim shape with predicate `same_entity_as`; the schema file is unchanged and no migration is needed for this predicate semantic. Schema validation runs on every save, and identity endpoint validation requires existing, distinct, same-kind base entity records on save, read, review, and correction. Full cross-record validation runs on reads, not generic saves, so incremental scan/extraction writes remain safe. `/api/v1/graph`, search responses, and entity details return `identity_groups`, `identity_suggestions`, and `identity_conflicts`. Only unsuperseded human `confirmed` or `asserted` links form symmetric read-time groups; exact-name same-kind matches and inferred identity claims are suggestions. Exact-name candidates normalize case and whitespace. `POST /api/v1/identity-candidates/review` verifies a current exact-name pair and appends a human claim for `confirmed`, `asserted`, or `rejected`, with empty evidence and no source provenance. Repeating the active judgment is idempotent; later judgments supersede prior pair judgments through the review chain, and an unconflicted rejected exact-name pair remains visible as a rejected human judgment with review actions, while a pair already surfaced as a conflict appears only in its conflict card. Search uses full claim history for identity review and conflicts; scenario graph compilation uses effective claims. Unsuperseded opposing human judgments and rejected pairs connected by confirmed paths are reported as conflicts, and conflicted connected components are withheld from groups. Reviews append records using the existing `reviewed_claim`/`supersedes` chain. The frontend shows groups, suggestions, conflicts, pair endpoints, available review state/provenance/evidence in selected entity details and Facts. Inferred-claim suggestions retain confirm/reject and same-kind endpoint correction through the existing claim APIs; exact-name candidates use the pair review operation. Identity review stays separate from alias review. Groups never rewrite entity IDs, aliases, typed deltas, or saved scenario selections, and scenario reads do not restore option-created entities that are absent from that scenario. Any incompatible schema shape change requires an explicit migration.

## Review log

Human reviews form an append-only log. `GET /api/v1/reviews` lists claim, alias, and identity judgments newest first with their effective and undoable state. `POST /api/v1/reviews/{record_id}/undo` appends a record whose optional `undoes` field reverts the current head of one review chain, restoring the prior judgment or original inference; non-head records return 409 and repeats are idempotent. The Facts page shows this log; each entry shows the prior state and an Undo action. See `docs/PORTABLE_FORMAT.md`.

The map visually projects only human-confirmed/asserted identity groups as one logical node. Original entity IDs, aliases, deltas, and scenario selections remain unchanged, and component details expose provenance from every group member. Inferred claims and exact-name matches remain separate. A non-rejected identity candidate may expose related alternatives with its unresolved status visible; human rejection or conflict blocks that navigation.

## Food-delivery example

`fixtures/food-delivery/` contains natural design, RFC, and decision Markdown for a fictional ordering, payment, restaurant, and courier workflow. Bootstrap it into a new disposable repository and run deterministic mock extraction without a model or Qdrant connection:

```sh
cd backend && UV_CACHE_DIR=/tmp/uv-cache uv run --locked --python 3.12 python ../fixtures/food-delivery/bootstrap.py /tmp/food-delivery
```

The offline scan extracts seven decisions from the Markdown, including order placement and geo/availability; it does not hand-seed decision records. Each option changes a context-specific queue, store, cache, or runtime resource, linked to a shared technology node. The Order Service database and the Analytics reporting PostgreSQL instance have distinct stable IDs and source passages; the geo alternative points directly to the reporting instance and cites both its option passage and the reporting context that identifies the instance. Repeated Order Service/Kafka references retain stable canonical IDs and evidence-backed aliases. Option evidence also includes a same-document actor passage when needed to support an inferred relationship. The menu-read RFC names no service actor, so its option changes the cache resource without inventing a service-to-cache edge. The example contains no preloaded identity groups, requires no model/provider configuration, and the target directory must be new or empty.

## Stdio MCP server

The backend package installs one console script, `switchplinth`. Without a command, it serves the HTTP API on port 8000. The `mcp` command serves the same four read-only MCP tools over stdio, with no Docker, Qdrant, or model required:

```sh
cd backend && uv run --locked --python 3.12 switchplinth mcp --repo /path/to/repo [--cache DIR] [--scan]
```

- `--repo PATH`: the repository with Markdown and `.decision/` (default: the current directory). A missing directory exits with an error. Opening a repository creates `.decision/schema/record-v1.schema.json`, `.decision/config.yaml`, and `.decision/instructions.md` when they are absent.
- `--cache DIR`: the disposable SQLite cache directory. The default is `$DECISION_CACHE` or `/tmp/switchplinth-cache`, plus a 16-character hash of the resolved repository path.
- `--scan`: run the deterministic mock extraction scan before serving. It writes inferred evidence, entity, decision, claim, and alias records under `.decision/`. Without `--scan`, startup rebuilds the indexes from existing `.decision/` evidence and writes no records, so an unscanned repository serves an empty graph.

Stdio keeps passage vectors in an in-process index, rebuilt at startup, instead of Qdrant. Unless exactly one non-Anthropic connection sets `capabilities.embeddings: true` with an `embedding_model`, the index uses deterministic token-hash vectors and search reports `semantic_index.mode: deterministic_local`; these vectors are not semantic embeddings. With exactly one such connection, startup and each search call that model; if it is unreachable, vector search reports an error and lexical search still answers.

To register it with an MCP client, use the command above with an absolute `--repo` path, or install the backend wheel and run `switchplinth mcp --repo PATH`. The server reports the MCP name `io.github.bcmyguest/switchplinth` and the package version from `backend/pyproject.toml`. To run it from Docker over the bundled food-delivery fixture, with no network, run `docker build -f Dockerfile.mcp -t switchplinth-mcp .` from the repository root and then `docker run -i --rm --network none switchplinth-mcp`.

## Portable data and generated state

Markdown and `.decision/` YAML are portable project data. Provider credentials are referenced through environment variable names such as `env:MODEL_API_KEY`; secret values are not written to YAML. Local `openai_compatible` endpoints may omit `credential_ref`; an explicit `env:` reference is preserved and used when configured. Blank optional connection fields are omitted from saved `model_connection` records. Inferred records retain evidence anchors and confidence, and human reviews are appended as superseding records.

SQLite is stored in the `decision-cache` volume and Qdrant data in `qdrant-data`. Both are rebuildable. `docker compose down -v` removes those generated volumes; it does not remove repository Markdown or `.decision/` files.

## Development checks

```sh
cd backend && uv run --locked --python 3.12 pytest -q
cd frontend && pnpm install --frozen-lockfile && pnpm typecheck && pnpm lint && pnpm build
```

The backend exposes deterministic mock extraction and a LiteLLM adapter for configured providers. Local `openai_compatible` endpoints can perform structured extraction and configured embeddings without an API key; hosted OpenAI and Anthropic connections still use their configured credentials. Provider extraction requests typed option deltas using the supported entity and relationship operations, including optional `expect: {}` or `expect: {exists: boolean}` preconditions; when a safe typed operation cannot be formed, the prompt requests `operations: []`. Unsupported or malformed generated operations trigger one bounded retry with schema feedback. The prompt lists known entity IDs with names. A relationship endpoint that names exactly one entity or alias (case- and whitespace-normalized), including an entity returned in the same response or added by the same delta, is mapped to that entity's ID before validation; ambiguous names, and unknown references while any entity is known, join the same retry with the valid ID/name list. References are never guessed. An invalid `alias_confidence` falls back to 0.65 with a diagnostic instead of rolling back the extraction. Invalid or ambiguous selections are rejected without coercion. If a record remains invalid after the bounded retry and the safely anchored-decision fallback is ineligible, it is not persisted and its diagnostic appears in the extraction completion summary; generated deltas are not otherwise rewritten. Repeated inferred decisions are collapsed only when the exact evidence anchor, complete normalized option labels, and selected label identify one unambiguous existing inferred record. Ambiguous same-passage candidates remain available for human review. Configure `embedding_model` with `capabilities.embeddings: true` to use provider embeddings for both Qdrant indexing and querying. Without that configuration, V0 reports that provider embeddings are unsupported and uses deterministic token-hash vectors as an offline fallback; those vectors are not semantic embeddings. A connection's optional `generation` object sets `reasoning` (`off`, `low`, `medium`, or `high`), `max_output_tokens`, and `request_timeout_seconds` (default 600) for extraction and delta proposal; for example `"generation":{"reasoning":"off"}` stops local reasoning models such as Qwen on Lemonade from spending the whole output budget on hidden reasoning and returning empty content. See `docs/PORTABLE_FORMAT.md` for the LiteLLM mapping. The connection form edits only `request_timeout_seconds` and keeps the other stored `generation` keys; set `reasoning` and `max_output_tokens` through `POST /api/v1/connections` or the YAML record, and send `"generation":{}` to clear the object. On hosted reasoning models `off` may be rejected, and hosted behavior is unverified. Use connection diagnostics to inspect endpoint and model connectivity before running provider extraction or proposal. For an HTTP-level check, the backend exposes `/health`, OpenAPI at `/docs`, and MCP streamable HTTP at `/mcp`. MCP provides `list_decisions`, `search_decisions`, `inspect_architecture`, and `inspect_entity`; HTTP `/mcp` and `switchplinth mcp --repo PATH` (stdio) expose the same tools. Stdio uses an in-process vector index instead of Qdrant but still calls a configured embedding model. Each tool accepts an optional `selections` map from decision ID to option ID.

### Navigation browser check

First bootstrap the fixture into a new or empty directory (`cd backend && uv run --locked --python 3.12 python ../fixtures/food-delivery/bootstrap.py /tmp/food-delivery`) and run the backend and frontend against that repository. Then `BASE_URL=<frontend URL> PLAYWRIGHT_MODULE=<playwright package dir> pnpm check:navigation` from `frontend/` clicks Architecture log "Explore full scenario" and waits until the What-if picker marks that decision current and focuses its active option, then asserts the map viewport and scenario selections are unchanged. Playwright is not a project dependency.

### Frontend layout

`frontend/src/App.tsx` is a shell: it creates the controllers and mounts the pages and dialogs. Controllers are hooks that receive their dependencies as arguments and return one object; views receive controllers as props.

- `app/`: hash navigation, theme, the workspace core (`useWorkspace`: graph, liveness, project, label catalog, repository generation), sidebar, top bar, and page heading.
- `features/architecture/`: Architecture page, map canvas, overlay panels (`useArchitecturePanels`), component detail, and map actions.
- `features/scenarios/`, `features/graph-editor/`, `features/facts/`, `features/explore/`, `features/discovery/`, `features/evidence/`, `features/settings/`, `features/repository/`, `features/architecture-log/`, `features/progress/`, `features/review-log/`: one feature each.
- `map/`: ReactFlow projection, layout, node and edge components, and the map and full-screen hooks.

A repository switch (`features/repository/useRepositorySwitch.ts`) calls each feature controller's `reset()` after the project opens; a failed open resets nothing.

## Scenarios

Saved scenarios load selections into the current graph and persist only under `.decision/scenarios/`. Scenario resolution keeps the last resolved selection for Save and grounded search while a new choice is pending; failed resolution restores those choices and leaves the graph intact. Repository switches invalidate pending scenario/list responses. Save includes an optional expected repository root, which the API checks before writing to the service captured by that request. The saved-scenario list reports loading, an empty successful list, or a visible error with Retry; refresh failures retain the last loaded list. The current scenario lifecycle supports create, list, and load; rename, update, and delete are not implemented and remain a product decision.

The Architecture map's What-if panel treats option changes as a temporary working preview and provides a one-click return to the repository's selected choices. It keeps the base choices and up to four recent resolved combinations in session-only history; selecting a history entry resolves that exact combination again, and switching repositories clears the history. A sticky decision picker stays available while browsing the option list; choosing a decision scrolls its choices and source into view and focuses the active choice. The panel summarizes the resolved graph changes, affected decisions, and assumptions without repeating the selected-choice list. **Save or reopen a named scenario** is a secondary action; saved scenarios persist under `.decision/scenarios/` and can be reopened from the same panel.

## Why-search grounding

For `why` searches about selected choices, the backend reports `grounded: true` only when effective claims cite the returned current passages. When passages exist without claim support, it returns the passages and labels the answer as not fully grounded. A why answer about an option absent from the selected scenario is also grounded when it returns that option's own current, indexed evidence (`context: decision_option`). A selected decision that involves a matched entity answers first, followed by unselected alternatives. An exact entity or alias match on an unselected option yields the unselected-option answer unless the query also names exactly an active entity that a selected decision involves. Entity and alias routing requires a complete multiword name, while single-word aliases remain searchable. Generic lexical searches retain passage-based grounding.

## Architecture page overlays

On the Architecture page, selecting a map component opens its details in a closable panel over the right side of the map. What-if and graph editing use separate closable overlays; selecting a map node while What-if is open replaces the scenario panel with component details, which provide a Return to What-if action. The desktop overlay backdrop leaves the map interactive; on mobile it provides an outside-click close target. Map instructions explain the node and edge cues, and scenario outcomes show choices, changes, affected decisions, and assumptions. Facts includes filters for identity candidates, rejected judgments, conflicts, claims, and aliases; its filters wrap on narrow screens. Map editing controls sit below the canvas. Opening a panel leaves the map's position and width unchanged. On mobile, panels use a near-full-width drawer. At desktop widths, the graph uses a separate 220px overview rail outside the React Flow node viewport, with a 12px gutter. Independent code and Playwright reviews verified no node/minimap overlap at 1440×900 after selecting SQS; the minimap is hidden at widths of 1024px and below. Escape closes the topmost overlay; closing source evidence returns focus to its passage trigger while leaving selected component details open. Explore now displays and announces supporting claims with cited passages. The final 12-criterion local V0 audit passed; evidence and limits are recorded in `docs/V0_PLAN.md`. Hosted-provider interoperability remains unverified; local model generation and embeddings were exercised for V1 (docs/V1_PLAN.md).

## Extraction review fallback

Provider extraction preserves a safely evidence-anchored, selected decision when generated typed option deltas fail validation: it stores empty active deltas and an `extraction_review` audit with the rejected JSON and validator errors. `/api/v1/decisions` exposes the review state, and the UI marks the decision and affected options after reload. A validated manual option edit clears only that option's audit item; the review flag remains until all listed options are resolved. The backend validates this optional field against the bundled v1 definition even when an existing repository has an older schema copy; it leaves that project file unchanged, so standalone validators need a deliberate schema refresh or migration. Older readers may ignore the field, while older writers that rewrite records can discard it; see `docs/PORTABLE_FORMAT.md`.

## Verification history

### Verified V0 checks

- Compose build/start: frontend, backend, and Qdrant healthy; backend `/health`, frontend `/`, and proxied `/api/v1/project` returned HTTP 200.
- Backend: the latest post-rebuild-fix locked suite passed 78 tests with 2 warnings in 87.74s (`uv run --locked --python 3.12 pytest -vv -x` from `backend/`). Earlier focused identity coverage passed 9 tests with 57 deselected.
- Frontend: from `frontend/`, `./node_modules/.bin/tsc -b`, `./node_modules/.bin/eslint .`, and `./node_modules/.bin/vite build` all exited 0.
- Navigation browser check: with the frontend running against a `fixtures/food-delivery` backend, `BASE_URL=<frontend URL> PLAYWRIGHT_MODULE=<playwright package dir> pnpm check:navigation` from `frontend/` clicks Architecture log "Explore full scenario" and asserts the map opens with What-if focused on that decision; Playwright is not a project dependency.
- Compose: `docker compose config` showed all published ports bound to `127.0.0.1` and the backend host-gateway mapping; disposable `docker compose run --rm --no-deps backend getent hosts host.docker.internal` resolved to `172.17.0.1`. The long-running services were stopped during this check.
- Compose acceptance: root verified 98 points in the root Qdrant collection and 7 points in a separate `examples` collection. Switching back without rescanning preserved grounded Kafka rationale/evidence. Kafka→SQS detail, picker traversal rejection, and MCP initialize/tools-list/query passed.
- Disposable fixture end-to-end: a synthetic Markdown source completed provider extraction through an OpenAI-compatible test endpoint, then SQLite/Qdrant indexes were rebuilt. The rebuild report reports nine canonical `.decision/` YAML files preserved and grounded evidence available before and after; it contains no per-file hashes. Hosted-provider interoperability remains unverified; V1 local-model verification is recorded in docs/V1_PLAN.md.
- Final V0 acceptance: all 12 local-scope criteria passed; the criterion matrix, exact evidence, and explicit limits are in `docs/V0_PLAN.md`. Criterion 10 independent proof: `<local review artifact>`. UX independent PASS: `<local review artifact>`, with desktop/mobile task flows, screenshots, source Escape/focus, edge geometry, contrast, and frontend checks. The UX Playwright API was mocked. Hosted-provider interoperability remains unverified; local model generation and embeddings were exercised for V1 (docs/V1_PLAN.md).

### Provider, browser, and durability checks

The provider adapters and diagnostics were exercised against a local OpenAI-compatible mock; no external provider credentials or external-provider diagnostics were tested. Provider-backed embedding calls used the same injected vectorizer for indexing and query. The bounded V1 local Gemma/Nomic gate passed on three repetitions of one explicit-choice fixture: all three first extractions persisted the selected SQS decision, two with `extraction_review`, and re-extraction added no decision. Each post-rebuild query was grounded and the human sentinel remained byte-identical. Re-extraction added one or two inferred claims per fixture with varied predicates or phrasing; broad recall and claim-level repeatability remain unverified. Hosted-provider interoperability is also unverified (docs/V1_PLAN.md). Independent browser checks exercised graph selection, evidence opening, and Kafka→SQS switching. A live Firefox switch with Kafka selected first retained the selected entity and updated its details to SQS rationale/evidence; the scenario diff displayed entity and relationship names. A live SQS search request returned grounded rationale/evidence and reported the deterministic-local vector fallback. The review opened a human-reviewed claim correction form and intercepted a Reject request to check its payload; it did not submit that request to the backend. `PortableRepository.save()` publishes each YAML record through a same-directory temporary file, flush/fsync, and atomic replace: after a process interruption, that record is either its complete old version or its complete new version. Ordinary exceptions remove the temporary file; abrupt exit before replacement can leave a hidden `.tmp` file. This guarantee is per record only: scan/provider work spanning records is not transactional, concurrent writers are not serialized, and power loss or storage-cache durability is not guaranteed. V1 schemas reject unknown versions; no v1-to-v2 migration exists, and any future schema upgrade requires an explicit migration.

### Final V1 suite

The final V1 backend suite passed `env UV_CACHE_DIR=/tmp/uv-cache uv run --locked --python 3.12 pytest -vv -s -o faulthandler_timeout=30` from `backend/` (88 passed, 2 existing deprecation warnings, 105.38s). Frontend typecheck, lint, and build passed after the preceding UI changes; the final extraction review fixes changed backend and documentation only. The live provider gate, review-needed browser screenshots, and remaining quality limits are recorded in `docs/V1_PLAN.md`.

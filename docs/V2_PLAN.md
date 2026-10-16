# V2 plan

## Goal

V2 is the food-delivery proof of concept in `fixtures/food-delivery/`. V2 has two goals of equal weight:

1. **The POC itself:** a natural, multi-document architecture corpus that the product extracts, maps, explains, and lets users compare alternatives over, without a model connection.
2. **Usability, usefulness, and shared components:** users complete real tasks on that corpus faster and with less friction, and the UI is built from common shared components (shadcn/ui primitives over semantic Tailwind tokens) instead of bespoke markup and ad hoc CSS.

Markdown and validated `.decision/` YAML remain canonical. SQLite, Qdrant, and graph projections remain disposable. V2 changes no schema version.

## Reference corpus

`fixtures/food-delivery/` holds nine Markdown files for a fictional ordering, payment, restaurant, and courier workflow, plus `bootstrap.py`:

- `docs/architecture/order-lifecycle.md`
- `docs/decisions/event-transport.md`, `docs/decisions/payment-retries.md`
- `docs/design/courier-dispatch.md`, `docs/design/order-placement.md`, `docs/design/reporting.md`
- `docs/rfc/geo-availability.md`
- `docs/rfcs/order-data.md`, `docs/rfcs/restaurant-menu-cache.md`

`bootstrap.py` copies the docs into a new or empty directory and runs the deterministic mock scan with Qdrant disabled; it requires no model or provider configuration:

```sh
cd backend && UV_CACHE_DIR=/tmp/uv-cache uv run --locked --python 3.12 python ../fixtures/food-delivery/bootstrap.py /tmp/food-delivery
```

The bootstrap asserts seven extracted decisions, one logical Order Service node, one logical Kafka node, distinct Order database (PostgreSQL) and `datastore-postgres-reporting` (Analytics reporting PostgreSQL) records, and no seeded identity groups. It hand-seeds no decision records. `backend/tests/test_domain.py::test_food_delivery_bootstrap_keeps_repeat_references_and_contextual_databases_distinct` covers it. The 2026-10-15 live baseline in `.tasks/ledger.md` reported 18 components, 7 decisions, 9 Markdown sources, and zero scenario conflicts or invalid assumptions.

## Starting state (measured 2026-10-15)

- `frontend/src/App.tsx` is 1,816 lines and holds every page. It contains 108 raw `<button>`, 17 `<input>`, 9 `<select>`, and 1 `<textarea>`; no other source file outside `components/ui/` contains raw controls.
- `frontend/src/components/ui/` contains three shadcn primitives: `button.tsx`, `dialog.tsx`, `select.tsx`. Later on 2026-10-15, nine primitives were added under `frontend/src/components/ui/`: `card`, `badge`, `tabs`, `input`, `textarea`, `sheet`, `tooltip`, `scroll-area`, `alert`. Tokens live in `frontend/theme.yml` and `frontend/src/theme.ts`.
- Page-specific CSS totals 870 lines: `map-readability.css` 407, `readability.css` 280, `styles.css` 158, `repository.css` 13, `correction.css` 12.
- Open items from the ledger: the 18-node map is dense and graph layout was explicitly deferred; the typography gate's fresh captures and interaction report are pending; Lemonade full and one-document extraction timed out (one run ended after 287s with an empty reply), which is inconclusive and not a model-quality result; scenario rename/update/delete is an unresolved product decision.

## Scope

- Food-delivery corpus as the reference fixture for every V2 UI gate.
- Shared component baseline and migration of all pages onto it.
- Behavior-preserving decomposition of `App.tsx`.
- Map readability at 18+ nodes.
- A scripted usefulness task study and the fixes it justifies.
- Scenario lifecycle, only after a product decision.
- User requests: (a) fullscreen map → increment 4; (b) readable map → increment 5; (c) Architecture log reasons → increment 6; (d) local Lemonade extraction → increment 7; (e) review log with undo → increment 8.
- Packaging and presentation: one-command demo → increment 11; stdio MCP server → increment 12; rename → increment 13; demo video → increment 14.

## Engineering rule

All refactor work (the `App.tsx` split, CSS retirement, backend restructuring) follows the `mattpocock-skills:codebase-design` skill: build deep modules (a small interface over a substantial hidden implementation) and place seams deliberately. Each worker report names the modules and seams it chose and why. Reviewers check the change against that skill.

## Out of scope

- A new canonical store. Postgres, Redis, Neo4j, or another canonical database stays out; SQLite and Qdrant stay disposable.
- Code-analysis extraction. The documented extension point with distinct code-derived evidence types stays unimplemented.
- Schema changes without an explicit, deterministic migration. V1 rejects unknown schema versions.
- Remote access or authentication; the API and MCP stay loopback-only.
- Claims about hosted-provider interoperability, general extraction recall, or claim-level repeatability.
- New source formats beyond Markdown.

## Increments

Each increment is one small, independently reviewable change with its own gate. Increments 3 and later run against a disposable copy of the bootstrapped food-delivery repository.

### 1. Plan and pointers

Add this file. Add a `README.md` and `CLAUDE.md` pointer to it after concurrent frontend/backend work in the shared tree lands, so the pointer edit does not collide with in-flight changes. Track progress in `.tasks/ledger.md`.

Gate: reviewer confirms every fact here against the repo or ledger.

### 2. Shared component baseline

Add the shadcn primitives the UI already imitates with bespoke markup: `Card`, `Badge`, `Tabs`, `Input`, `Textarea`, `Sheet`, `Tooltip`, `ScrollArea`, `Alert`. Style them only with semantic tokens from `theme.yml`/`theme.ts`; no raw color values. Do not migrate pages in this increment.

Gate: typecheck/lint/build pass; each primitive renders on a defined surface (a dev-only preview route or a test render) in light and dark themes with visible hover, focus, selected, and disabled states and no color-only state cue.

### 3. Split `App.tsx` and migrate controls

Split `App.tsx` by page with no behavior change: Architecture map, Architecture log, Progress, Facts, Scenarios, Explore, and shared overlays (component details, What-if, graph editor, source evidence dialog). Replace raw controls with primitives. Retire ad hoc CSS into Tailwind utilities and tokens. Land one page per change so each diff stays reviewable.

Gate per page: existing tests unchanged and green; the page's prior browser gates (overlay geometry, Escape/focus return, source passage, no horizontal overflow) re-run at 1440×900 and 375×812 in both themes. Final gate: `App.tsx` is a shell of at most 200 lines with no page markup, event handlers, or API calls.

Dead-code removals (knip gate, 13 findings to 0). These reverse part of increment 2's baseline:
- `Sheet`: map overlays are deliberately non-modal; a Radix Dialog adds a focus trap, closes on outside interaction, and portals content out of the map layout.
- `ScrollArea` and `@radix-ui/react-scroll-area`: scroll logic calls `scrollTo` on the native What-if picker and source-document scrollers; an inner viewport breaks it.
- `Tabs` and `@radix-ui/react-tabs`: no tabbed surface exists; pages use hash navigation and Facts filters are `aria-pressed` buttons.
- `Tooltip` and `@radix-ui/react-tooltip`: needs an app-level provider and hover-only content over the map without a gate; icon buttons already carry accessible names.
- `Input` and `Textarea`: unused until the control migration adopts them; restore them from git history then.
- `CardAction`, `CardFooter`, and the `export` on the `Alias`/`Relationship` types (still used inside `types.ts`): no external caller.
- `.avatar` and `.avatar.mini` CSS rules: no markup uses them.

### 4. Map fullscreen (request a)

Requirement: a button puts the map container into fullscreen through the Fullscreen API, with a fixed-inset fallback where the API is unavailable. The button and Escape exit. Details, What-if, and editor overlays work inside fullscreen. Exit restores the prior viewport and returns focus to the button. A plan-time grep found no fullscreen code in `frontend/src/`.

Gate: enter, use each overlay, and exit at 1440×900 and 375×812 in Chromium and Firefox.

### 5. Map readability for 18+ nodes (request b)

Lay out the projection with elkjs (layered algorithm). Route orthogonal edges between fixed ports/handles. Group nodes in containers by entity kind. Hover or selection dims non-incident edges and unrelated nodes to ≤0.3 opacity and widens incident strokes, so state never depends on color alone. Edge-label density depends on zoom. Keep source IDs and typed deltas unchanged; remap only rendered nodes/edges. Never merge by display name. `frontend/package.json` had no layout library at plan time.

Gate at 1440×900 and 375×812: zero node bounding-box intersections; edge crossings reduced ≥50% against a baseline count recorded before the change; every edge segment orthogonal; edge labels ≥12px at fit zoom; on hover and selection, non-incident edges and unrelated nodes measure ≤0.3 opacity and incident edges have a wider stroke; minimap rules unchanged; canvas position/width unchanged when overlays open.

Backlog (Map/What-if): scenario added/removed lists compare against the base graph, not the previous selection. Consider a "diff vs previous selection" view in What-if.

### 6. Architecture log reasons (request c)

Schema v1 options carry only `id`, `title`, `rationale`, `evidence`, and `delta` (`backend/src/switchplinth/record-v1.schema.json`); no consequences or rejection fields exist. In the fixture, 6 of 9 docs have a `## Consequences` section and 7 have an alternative section. Derive displayed consequences and rejection reasons from cited source passages; change no schema.

Gate: all 7 decisions render rationale, each alternative with its rejection reason where the source states one, consequences where present, and working passage links.

Result: done (backend `d23ee3c`, UI `3f0ea73`). Each decision shows its rationale, each alternative's "why not chosen" reason where the source states one, and consequences where present, with passage links. Reasons follow the saved choice; the log labels a previewed What-if alternative as previewed, never as rejected. Reviews: `<local review artifact>` and `review-ui.md`, backend PASS on re-review, UI PASS.

### 7. Local model extraction (Lemonade) (request d)

Use the registered `openai_compatible` connection `lemonade-qwen38`; this supersedes the ledger's earlier "removed" line. Its endpoint and model live in the disposable connection config, never in committed files. Run extraction only on a disposable copy.

The food-delivery mock extraction uses fixture-tuned phrase rules in `backend/src/switchplinth/service.py` (for example, the hard-coded `datastore-postgres-reporting`). The sample therefore demonstrates the delta/scenario model, not extraction quality. This increment records a real local-model extraction on a disposable copy against the mock: decision, entity, and relationship counts, misses, and extras. README, demo captions, and docs must say "fixture-tuned mock extraction".

Gate: all six diagnostics pass; one-document extraction, then full-corpus extraction, each completes within a recorded timeout or records its failure; the model-vs-mock comparison is recorded; canonical `.decision/` hashes unchanged. Make no recall claims.

### 8. Review log with undo (request e)

Show an append-only log of human claim, alias, and identity judgments. Undo appends a superseding record that restores the prior effective state; each log entry shows that prior state.

Gate: confirm → undo → re-confirm passes for a claim, an alias, and an identity link; original inferred records stay byte-identical.

Result: done (backend `314c199` and `cd7d0e5`, UI `5fa52b6`). The Facts page shows the append-only log of human claim, alias, and identity judgments; each entry shows its prior state and an Undo action. Reviews: `<local review artifact>` and `review-ui.md`, backend PASS on re-review, UI PASS.

### 9. Usefulness task study

Script 3–4 food-delivery tasks. Record the baseline before UI increments change behavior: pre-V2 map and Architecture log captures in `<local review artifact>`, plus any task runs, each from a fresh load, done before increment 3 lands. Later runs compare against this baseline.

- "Why did the team choose SQS for payment retries?" — reach the rationale and open the source passage.
- "What changes if we pick the geo/availability alternative?" — preview it, name the changed entities/relationships and affected decisions, return to base.
- "Triage the inferred facts" — confirm, reject, or correct items in Facts without losing map context.
- Optional: "Which decisions touch the Order database (PostgreSQL)?"

Record per task: success or failure, click count, time, and each friction point with a screenshot. Findings drive scoped fixes; each fix re-runs the task that exposed it.

Gate: baseline and post-fix results tables recorded in this file; no fix lands without a before/after measurement against that baseline.

Baseline, recorded 2026-10-16 on `b8e5053` (pre-V2 frontend), Chromium headless at 1440×900, against a disposable food-delivery copy (`<local review artifact>`). Wall time is automated script time, not human time; compare it only against reruns of the same script.

| Task | Success | Clicks | Wall (s) |
| --- | --- | --- | --- |
| 1. Why SQS for payment retries? | yes | 2 | 0.2 |
| 2. Preview geo/availability alternative, name changes and affected decisions, return to base | partial | 3 | 4.7 |
| 3. Triage inferred facts (confirm 1, reject 1, correct 1) keeping map context | yes | 8 | 6.3 |
| 4. Which decisions touch Order database (PostgreSQL)? | yes | 1 | 0.1 |

Baseline friction:

- F1 (task 1): SQS details list 3 linked decisions; two are unselected alternatives, and the active payment-retry decision appears last.
- F2 (task 2): no decision title says "geo"; only the source filename `docs/rfc/geo-availability.md` identifies the 7th decision. The What-if panel covers the map's right side and needs an internal scroll.
- F3 (task 2): the outcome reports "17 records" changed and "7 decisions" affected for a one-decision change, and lists every node/edge without added/removed markers. The user cannot name the real delta (one Redis cache and its edges removed, one reads_from edge added, 1 decision affected). This makes task 2 partial.
- F4 (task 2): no reset control; the user re-picks the original option, and nothing confirms the baseline is restored.
- F5 (task 3): a selected component's details overlay covers the "Needs a closer look" button.
- F6 (task 3): Facts has no map; rows use icon-only buttons and hide the evidence passage until Correct opens, so confirm and reject happen blind.
- F7 (task 3): "Redis mentioned in docs/rfcs/order-data.md" appears twice with identical text.
- F8 (task 3): the correction form shows raw IDs and snake_case predicates.
- F9 (task 4): most nodes sit below the 900px fold, and several labels are truncated.

### 10. Scenario lifecycle

Rename, update, and delete of saved scenarios. Blocked on a product decision about whether users need them. If approved, persist only under `.decision/scenarios/` and keep create/list/load behavior intact.

Gate: product decision recorded here before implementation.

### 11. Try it: one-command demo

`scripts/demo.sh` bootstraps the food-delivery fixture and starts the stack with one command. Ports are configurable through environment variables. Fix the pnpm `allowBuilds` setting so a clean install builds. Rewrite the README opening for a first-time human reader.

Gate: a reviewer runs `scripts/demo.sh` from a clean copy of the repository and reaches the map without other setup steps.

### 12. Stdio MCP server

`switchplinth mcp --repo PATH` (formerly `decision-graph-backend mcp`) serves MCP over stdio for one repository. Add a `list_decisions` tool and improve the tool descriptions. The wheel builds with the entry point. HTTP `/mcp` and stdio share `create_mcp_server` in `mcp_tools.py`, so both expose the same four tools and descriptions. `DecisionService` takes a `VectorIndex` (`rebuild`, `search`; defined in `store.py`): Qdrant is the default adapter, and stdio passes the in-process `LocalVectorIndex`. Stdio still calls a configured embedding model for index rebuild and each search; when the model is unreachable, vector search reports an error and lexical search still answers. No `--no-model` flag exists.

Gate: an MCP client lists and calls every tool over stdio against the bootstrapped fixture; the built wheel installs and runs the command.

### 13. Rename

Apply the product name **Switchplinth** to the UI label, README, docs, package and CLI names, and page title. Centralize the names so the next rename touches one place per layer. Target identifiers: GitHub repository `bcmyguest/switchplinth`; PyPI package and import `switchplinth`; CLI `switchplinth` (for example `switchplinth mcp --repo PATH`); MCP server name `io.github.bcmyguest/switchplinth`; Compose project and images `switchplinth`; demo Compose project and cache directory `switchplinth-demo` (formerly `decision-graph-demo`); private frontend package `switchplinth-frontend`. All target identifiers except the GitHub repository are applied in the working tree. Product identifiers are centralized in `backend/src/switchplinth/__init__.py` and `frontend/src/brand.ts`. Tests import `switchplinth`; the temporary `decision_graph` alias package has been removed. The `DECISION_*` environment variables keep their names. The portable format (`.decision/`, `schema_version: decision/v1`, record types, schema file names) and the `Decision` domain term keep their names.

Gate: a grep finds no old product name outside history and changelog entries; backend suite and frontend typecheck/lint/build pass.

### 14. Demo video

Record a 45–75s walkthrough with Playwright `recordVideo` at 1440×900, with captions. Write an MP4 under 10MB and a GIF under 5MB to `<local review artifact>`. This is the last increment.

Gate: a reviewer checks pacing and caption legibility, and confirms that nothing shown is mocked without saying so or overstated (captions say "fixture-tuned mock extraction").

## Acceptance criteria

- No raw `<button>`, `<input>`, `<select>`, or `<textarea>` outside `frontend/src/components/ui/`.
- `App.tsx` reduced to a shell of at most 200 lines: routing, providers, and page composition only; no page markup, event handlers, or API calls.
- Each of the five page-specific CSS files is removed or carries a one-line justification for what tokens and Tailwind cannot express.
- Locked backend suite passes: `uv run --locked --python 3.12 pytest -q` from `backend/`. Frontend `tsc -b`, ESLint, and Vite build pass.
- Desktop 1440×900 and mobile 375×812 reviewed in light and dark themes for every page, with screenshots inspected by a reviewer other than the implementor.
- Food-delivery bootstrap still asserts seven decisions and distinct PostgreSQL identities.
- Task-study results recorded with success, click count, and friction per task.
- Dead-code gate: run knip (or ts-prune) on the frontend and vulture (or ruff unused-code rules) on the backend through pinned tools or one-off runners; add no permanent dependency unless the review justifies it. Remove or justify in review every unused export, file, component (including shadcn primitives still unimported at the end of V2), dependency, and stale fixture.
- Refactor worker reports name the modules and seams chosen and why, per the engineering rule.
- Each reviewed increment ships before/after screenshots (1440×900 and 375×812; light and dark where UI changed) in `<local review artifact><increment-slug>/` with a `summary.md`.

## Status

| Increment | Status |
| --- | --- |
| 1. Plan and pointers | Done: plan written; README and CLAUDE.md point to it |
| 2. Shared component baseline | Primitives added; static review PASS; render gate pending |
| 3. Split `App.tsx` and migrate controls | Not started |
| 4. Map fullscreen | Done (`00b04ed`); re-review PASS |
| 5. Map readability | Done (`00b04ed`); review PASS (Chromium and Firefox: 0 overlaps, crossings 38→4 and 61→4, all edges orthogonal) |
| 6. Architecture log reasons | Done (backend `d23ee3c`, UI `3f0ea73`); reviews PASS |
| 7. Local model extraction (Lemonade) | Connection registered; extraction gate pending |
| 8. Review log with undo | Done (backend `314c199`, `cd7d0e5`; UI `5fa52b6`); reviews PASS |
| 9. Usefulness task study | Baseline recorded on `b8e5053`; fixes pending |
| 10. Scenario lifecycle | Not started; needs product decision |
| 11. Try it: one-command demo | Implemented; clean-copy review pending |
| 12. Stdio MCP server | Implemented; HTTP `/mcp` switch and vector-backend seam pending |
| 13. Rename | Committed (backend `263d875`, frontend `00b04ed`); tests migrated to `switchplinth` and the `decision_graph` alias removed; GitHub repository rename pending |
| 14. Demo video | Not started; last increment |

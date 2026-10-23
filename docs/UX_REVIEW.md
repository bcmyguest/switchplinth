# V0 usability review

This is a working review of the current V0 experience. Functional browser gates prove that the map, overlays, evidence links, scenario switching, and review actions work. They do not prove that a new user can understand the interface or complete the main tasks without guidance.

## Primary task flows

1. Open a repository and understand what the system thinks it found.
2. Select a component and answer why it exists.
3. Switch one decision option and understand what changed.
4. Inspect and resolve an uncertain fact without losing map context.
5. Ask a grounded question and open the supporting passage.

## Current usability risks

The primary implementation surfaces are `frontend/src/App.tsx` (page structure and task actions) and `frontend/src/readability.css` (responsive layout and overlay behavior). Future implementation tasks should keep these concerns aligned instead of adding more page-specific exceptions.

### Map orientation

The map has several competing controls, legends, counters, and assistant content before the graph. A first-time user needs a short explanation of what the nodes and edge styles mean and one obvious next action. Empty and low-confidence states should explain what to do next.

### Overlay recovery

The desktop panels now overlay the map correctly. At 375px they cover most of the canvas, so the panel needs a strong title, a visible close action, a backdrop or equivalent focus treatment, and a compact selected-item summary. Closing should return the user to the same map position and selected item.

### Scenario comprehension

The What-if panel should lead with the selected option, then show changed entities and relationships, affected decisions, invalid assumptions, and evidence. Counts need plain grammar (`1 decision`, not `1 decisions`) and a distinction between zero changes and an analysis that has not run.

### Facts triage

The review queue can become a long undifferentiated list. Group direct candidates, rejected judgments, and transitive conflicts; show why each item is present; keep identity review separate from alias review; and preserve graph-wide visibility when a selected entity has no local candidates.

### Evidence hierarchy

Users need to see rationale and an `Open passage` action before internal IDs, model names, and confidence details. Source paths must wrap at narrow widths. Epistemic state should be visible without requiring a tooltip.

## Review gate

For this review, agent implemented the changes and a separate agent reviewer checked the final result. The gate required Playwright task flows at 1440px and 375px, root screenshot inspection, keyboard and Escape behavior, no horizontal overflow, frontend typecheck/lint/build, and assertions that each primary task reached its intended outcome; geometry-only assertions were not sufficient. Results are recorded below.

## Completed review gate — 2026-10-12

The ranked review was implemented and independently rechecked. Final verdict: PASS in `<local review artifact>`.

- First-use map guidance and node/edge legend; desktop What-if interaction transitions exclusively to selected-component detail and offers a Return to What-if action.
- Scenario comparison presents selected choices and outcomes with correct count grammar. Facts filters wrap at 375px. Evidence actions open the cited passage.
- Escape closes the topmost source dialog while retaining component detail and returning focus to its exact passage trigger; the next Escape closes detail and returns focus to the map node. What-if dismissal also returns focus after the panel transition settles.
- Desktop and 375×812 Playwright task flows passed. The flow verifies Kafka→SQS changes, a confirmed Facts action, grounded Kafka search under the selected scenario, passage opening, panel recovery, Assumptions access after mobile scrolling, and zero horizontal overflow. The API was mocked in this UX harness.
- Edge geometry check passed for Kafka and SQS: desktop labels clear cards and handles, all three cards remain visible/clickable beside the minimap rail, and the mobile label is visible between cards without overflow. Computed contrast audit: 200 visible normal-weight text nodes across six states, zero below 4.5:1, minimum 4.6045:1.
- Frontend checks passed: `./node_modules/.bin/tsc -b`, `./node_modules/.bin/eslint .`, and `./node_modules/.bin/vite build` (1,896 modules). Root inspected the screenshots listed in the independent verdict.

Evidence: task flow `<local review artifact>`; edge measurements `<local review artifact>`; Escape regression `<local review artifact>`; contrast `<local review artifact>`; screenshots are enumerated in `<local review artifact>`.


## Follow-up review — temporary scenario exploration

### User outcome

People should be able to change decision options from the map and inspect the resulting graph immediately. These changes are a temporary working scenario by default. Saving creates a named scenario that can be shared or reopened; it is not part of checking an option.

### Design direction

- Make the active working scenario and its temporary state clear from the map.
- Keep option switching direct, preserve the selected map context, and show the resulting graph, affected decisions, assumptions, and source evidence as resolution completes.
- Treat return to the repository's selected choices as an obvious recovery action when a user is exploring alternatives.
- Put save behind an explicit share/save action with language that explains it creates a named reusable scenario. Saved scenarios remain available to reopen, but should not compete with option switching as the primary task.
- Consider recent changes or comparison shortcuts only where they reduce steps in trying, comparing, and returning from options; avoid adding controls without a demonstrated task benefit.

### Acceptance evidence to collect

Reproduce the current map and What-if flow in a live browser at 1440×900 and 375×812. Capture screenshots and inspect them. Then verify that option changes remain temporary, update the map and scenario evidence, can be undone by returning to the base choices, and save only when the user chooses the named sharing action. Check keyboard recovery and horizontal overflow at both sizes. Record the exact backend/API requests and focused frontend/API checks.

### Baseline captured (2026-10-15)

Playwright screenshots were captured from an isolated Vite process with the demo graph, at exact 1440×900 and 375×812 viewport sizes. The What-if panel measures about 390×693px on desktop and 351×658px on mobile. At mobile size it leaves only a narrow visible strip of the map, and current choices/outcome sections begin below the option controls. The panel exposes no direct action to restore repository-selected choices. The “Save scenario” action is visible beside the panel title, even though demo mode disables it. There was no horizontal overflow. No scenario API requests were sent during the baseline. Captures: `<local review artifact>`, `<local review artifact>`, and the two full-page `what-if-*.png` captures.

### Session-only combination switching

Option buttons already let people compose choices across several decisions. Add a small in-session history of resolved choice combinations so a person can move between recent previews with one click. Seed it with the repository's current choices; append a history entry when a changed combination resolves successfully; selecting a history entry resolves that same selection map again. Keep the history in the browser session only and clear it on repository switch. Do not write history entries as portable scenarios.

The acceptance flow must change options for two decisions to create a combined preview, make another combination, and switch back and forth between those exact combinations from the map without saving. The history labels must identify the combinations clearly, and the selected choice, compiled graph, source/rationale, affected decisions, conflicts, and invalid assumptions must match each selected entry. A separate one-click return to the repository's original choices remains available.

### Live browser review — 2026-10-15

The first isolated live API run used disposable fixture copies and confirmed the two-decision SQS+PostgreSQL and SQS+Redis selections, exact history replay, keyboard activation, source evidence focus recovery, no scenario save during exploration, and one portable save after the explicit named-save action. The saved selection reopened correctly, desktop/mobile document overflow was absent, and root `.decision/` hashes were unchanged. The report is `<local review artifact>` and the screenshots are in the same directory.

Root inspected the 1440×900 and 375×812 captures and found that the history controls and outcome summary were below the visible scenario panel at desktop; the mobile view also hid the fourth decision. This places the quick-switch action out of view during the main task, so the browser acceptance gate remains open. The next review must place a compact base/recent-combination switcher and concise result summary near the top, then capture and inspect fresh screenshots at both sizes. The first Playwright process emitted a pending entity-detail route error during close. The corrected gate drained the route and exited cleanly with no assertion failures.

The visibility follow-up placed the switcher and summary above option rows; root confirmed both were visible in fresh desktop and mobile screenshots. Root found a second readability problem in those captures: history tiles repeated all four decision selections and became dense, while two-column mobile option buttons split words.

The final pass shows only choices that differ from the repository baseline in recent labels, shortens generic visible choice names while retaining full accessible labels/titles, and gives the compact base row a visible divider before “Original choices.” At 375px, recent combinations and option buttons are stacked at full drawer width; the option status remains legible and does not wrap into words. Independent source review passed.

Root inspected and accepted fresh screenshots from the current source at `<local review artifact>` and `<local review artifact>`. The live gate used an isolated backend with disposable fixture copies and ran Vite/API/Playwright in the same network namespace. It verified the SQS+PostgreSQL and SQS+Redis combinations, exact history A↔B switching by mouse and keyboard, return to repository choices and reopening a recent combination, matching graph/detail/evidence and outcome data, source-dialog Escape focus return, and no horizontal overflow. No `/scenarios` save request occurred during temporary exploration. Exactly one portable scenario write followed the explicit “Save as named scenario” action and that saved selection reopened. The complete request/response and bounds report is `<local review artifact>`; `.decision/` hashes matched the pre-run snapshot.

The final 1440×900 drawer ends at y=876; history ends at y=419 and the preview summary at y=508. At 375×812 the drawer ends at y=800; history ends at y=459 and the summary at y=541. Mobile choice buttons measure 313px wide, with normal word breaking and 12px status labels. Frontend `./node_modules/.bin/tsc -b`, `./node_modules/.bin/eslint .`, `./node_modules/.bin/vite build` (1,897 modules), and `git diff --check` passed. This acceptance covers the synthetic live fixture, not a production repository. The worktree also contains unrelated pre-existing edits; `frontend/tsconfig.tsbuildinfo` was already modified before the final gate and remains a tracked generated compiler cache change.

### Follow-up: direct navigation between decisions in the map overlay

The combination history makes it easy to return to a previously resolved set of choices, but it did not directly navigate among individual decisions. A sticky horizontal picker now remains reachable inside the scrollable What-if drawer. Each decision button scrolls the actual decision and its options into view, updates the visible current chip, and focuses the first enabled option. Picker focus and navigation do not change scenario selection or map state. Visible chip labels use concise decision names such as “Event transport” and “Order database”; the full title remains available in the title and accessible name. When the active decision changes, the picker scrolls its horizontal list so the complete active chip and Current marker remain visible without moving the drawer or map.

Independent source review passed. The final live browser gate at `<local review artifact>` used a disposable fixture and passed at 1440×900 and 375×812. The fourth decision began below the mobile drawer (y=917–1067, drawer bottom 800); keyboard Enter on its chip moved it into view (y=609–759), left the picker sticky and visible (y=158–205), and focused its active PostgreSQL option. Choosing Redis then kept the decision and source visible (y=396–546). All four chips were reachable with Tab; horizontal pointer scrolling exposed and activated the fourth chip without resolving or saving. The computed React Flow viewport transform was identical before and after decision navigation, the temporary choice generated one ordinary `/scenarios/resolve` request, and no named-scenario write or horizontal overflow occurred. At 375×812 the active chip bounds are x=186–348 and scroller bounds x=80–347 (1px layout rounding tolerance); the Current marker at x=292–339 is fully within the scroller. After selecting Redis, the chip bounds are x=185–347 and marker x=291–338. Root inspected and accepted the final captures: `<local review artifact>` and `<local review artifact>`.

Final checks passed from `frontend/`: `./node_modules/.bin/tsc -b`, `./node_modules/.bin/eslint .`, `./node_modules/.bin/vite build` (1,897 modules), and `git diff --check`. This browser acceptance exercises a synthetic disposable fixture, not a production repository.

### Follow-up: component alternatives, rationale, and theme readability (2026-10-15)

Selecting the courier availability cache now opens its linked RFC decision in the component overlay, with Redis marked as selected and reporting PostgreSQL marked as an alternative for that decision. The alternative's title, source rationale, cited-passage action, and direct `Preview this option` control appear on the first click. Previewing changes the graph and option status without a saved-scenario write; the Redis option is immediately available to switch back. Architecture log and Scenarios show the selected option's source-backed reason and passage link.

A persisted light/dark theme control applies semantic tokens to the map, component panel, Architecture log, and Scenarios. The focused browser run at 1440×900 and 375×812 verified theme persistence across routes, selected/alternative labeling, direct preview and click-back, source dialog focus entry and Escape return, mobile first-fold scenario option/rationale/source visibility, keyboard focus styling, and no horizontal overflow. Root and independent screenshot review accepted `<local review artifact>`; the light CTA contrast follow-up is in `<local review artifact>` and was reviewed independently. Its light primary CTA measures 6.75:1, and the source dialog mobile capture shows the title/path and highlighted passage. Frontend typecheck, lint, and build passed.

This scoped pass improves decision and control readability, not the density of the 18-node fixture map; small metadata labels remain. Provider diagnostics for the offered Lemonade connection succeeded, but full-corpus extraction (287s) and one-document extraction (90s) produced no response. A direct 20-token chat completion also timed out at 30s while Lemonade reported the model busy. The app/LiteLLM proposal probe returned HTTP 502 before reaching the model because the proposal path supplied no API key (`Missing credentials`), even though the local connection is configured keyless; its temporary connection record was removed. These results identify provider-path/inference responsiveness and a separate LiteLLM credential-path issue, but do not establish model extraction quality. Lemonade was not made a product default and no machine-specific URL was committed.

## Use-case review against the live backend — 2026-10-23

A live review drove the food-delivery fixture through the backend and Vite at 1440×900 and 375×812 instead of a mocked API. Findings and fixes:

- **Scenario switching felt broken because every read was slow.** Each graph, resolve, diff, and entity read re-parsed every `.decision/` YAML file several times (about 600 parses per request), so a 9-document repository took 2–4 s per request and one What-if switch issued four of them. `PortableRepository` now reuses validated parses of unchanged files (keyed by inode, size, mtime, and the overlay schema text, returned as copies) and `load_yaml` uses the libyaml safe loader when available. Resolve fell from 2.65 s to 0.15 s; `/api/v1/graph` answers in about 40 ms.
- **Returning to repository choices duplicated the base history entry.** The pinned base was also added as a recent combination, which rendered two "Original choices" rows and a React duplicate-key error. The base is no longer added as a recent entry.
- **Scenarios page results were below seven decision blocks.** At widths of 1200px and above the page now shows the options on the left and a sticky results column (history, preview counts, changes vs previous choice, comparison with repository choices, named scenarios) on the right. The page link text no longer refers to a component rationale that the page does not show.
- **Explore "Try asking" chips only filled the input.** They now ask immediately, and they are generated from the current choices that name a map component (for example "Why Amazon SQS?") instead of fixed Kafka/SQS questions.
- **Lexical search dropped words followed by punctuation**, so "Which decisions mention replay?" searched without "replay" and found nothing. The SQLite index now tokenizes on word characters.
- **Map edits went to an unrelated decision.** "Remove selected" and other canvas edits staged their operation in the first decision unless an editor draft was open. They now target the decision whose selected option (then any option) touches the component; an open draft keeps its target.
- **Scenarios drew duplicate technologies on the map.** The compiled graph keeps every base entity, so after Kafka→SQS the map still showed a disconnected Apache Kafka card beside Amazon SQS (and PostgreSQL beside Redis after the order-data switch), which read as both being in use. The map projection now omits components that have no relationship in the current scenario, appear in some option delta, and appear in no selected option. A "Show N unused alternatives" toggle in the map summary reveals them; graph, search, and component details are unchanged. With the repository choices this hides the Analytics reporting PostgreSQL card, which only the geo/availability alternative uses.
- **Facts and review-log actions were indistinguishable to assistive technology.** The 43 "Confirm claim" buttons and every "Undo" button now include the item in their accessible name, and Correct reports `aria-expanded`.

`frontend/e2e/use-cases.check.mjs` (`pnpm check:use-cases`) covers these flows; it fails on the previous frontend at the duplicate history entry. The existing navigation, capability, and scenario-diff checks also pass against the live backend; scenario-diff previously did not finish within 30 minutes on the slow backend.

Remaining observations, not changed here: the 18-node map still truncates long labels at fit zoom; decision titles extracted from RFCs keep their `RFC:` prefix; the Facts "All" filter counts reviewed rows while the heading counts only pending ones; and saved scenarios still list only their names.

### README images from the running app — 2026-10-23

The README hero was a five-node SVG illustration from the site, not the product, and its "Repository selection" frame showed Amazon SQS where the sample's repository choice is Apache Kafka. The other README screenshots predated the scenario fixes. `site/scripts/app-screenshots.mjs` now captures every README image from the running app on a fresh food-delivery bootstrap, including a two-frame GIF of the real map and What-if panel switching order events Kafka → SQS.

Capturing them exposed three product issues, fixed here:

- Map cards clamped names such as "Order event stream (Amazon SQS)" to "Order event stream…", hiding the very part a scenario switch changes. Cards now show a trailing parenthesized implementation on its own line ("Order event stream" / "Amazon SQS"), and nodes are 232×112 graph units (from 216×96). The full name stays in the card's title.
- Explore listed one card per cited passage for the same fact ("Apache Kafka · mentioned in · decisions/event-transport.md" three times). Claims with the same subject, predicate, object, and review state now share one card that quotes every passage. Passage rows are left-aligned instead of centered.
- Jumping to a decision in What-if centered it, so a decision taller than the panel slid its title and first option under the sticky header. The jump now aligns the decision's top just below that header.

The use-case, navigation, capability, and scenario-diff checks pass after these changes, as do frontend typecheck, lint, and build.

---
title: Up next
description: What works today, and the next steps - hosted-provider tests, recall measurement, extraction beyond the sample, authentication, more formats, richer conflicts, scenario lifecycle.
---

## Works today

- `switchplinth setup` sets up a repository or the sample, runs the first scan, and registers the MCP server with Claude Code, Claude Desktop, Cursor, or VS Code.
- `./scripts/demo.sh` runs the food-delivery sample in Docker with one command.
- Markdown discovery with no template; canonical, portable `.decision/` YAML; SQLite and Qdrant indexes that rebuild from those files.
- Deterministic mock extraction, and model extraction through local OpenAI-compatible servers. A local Qwen3.8 model with reasoning off found all 7 decisions in the sample.
- Confirm, reject, and correct for claims, aliases, and identity links; the Facts page shows the review log with Undo on each entry.
- An architecture map with layered layout and fullscreen mode, plus What-if previews that switch decision options in place.
- An Architecture log with each decision's rationale, why alternatives were not chosen, and consequences, linked to source passages.
- Grounded "why" answers with cited passages.
- Four read-only MCP tools over streamable HTTP (loopback) and stdio.

## Up next

These are the next steps, in no particular order and without dates.

| Next step | Where it stands today |
| --- | --- |
| **Test hosted providers** (OpenAI, Anthropic) | Adapters exist; no hosted credentials or diagnostics have been exercised. |
| **Measure extraction recall on more repositories** | Local-model results cover small fixtures and the bundled sample only. Claim-level repeatability is unmeasured. |
| **Extraction beyond the sample** | The one-command demo uses mock rules tuned to the sample's text; it shows the decision and what-if model, not extraction quality on other documents. |
| **Authentication for remote API and MCP access** | Both are unauthenticated and bind to loopback; keep them local. |
| **More source formats** | Markdown only; no code, PDFs, or other formats. |
| **Conflict detection beyond same-ID writes** | The compiler reports a conflict only when two selected options write the same entity or relationship ID. |
| **Scenario rename, update, and delete** | Saved scenarios support create, list, and load. |

Other current boundaries are documented where they apply: the embedding fallback in [Model providers](../providers/), and write safety and schema versioning in [Portable format](../portable-format/).

---
title: FAQ
description: Answers on templates, where data lives, model requirements, re-extraction safety, remote access, and what the sample does and does not show.
---

## Do my docs need an ADR template?

No. Discovery reads ADRs, RFCs, design notes, READMEs, and other Markdown without a required format. `.decision/instructions.md` can hold optional extraction hints.

## Does it change my Markdown?

No. Source Markdown is read-only input. The app writes its records to `.decision/`.

## Where does my data live?

In your repository: Markdown plus validated YAML under `.decision/`. Commit it like any other text. SQLite and Qdrant hold rebuildable indexes in Docker volumes.

## Do I need a model or an API key?

No. Deterministic/mock extraction runs without a model. Local OpenAI-compatible servers work without a key. Hosted providers need a credential through an environment variable, and that path is untested.

## Will re-running extraction overwrite my reviews?

No. Human-reviewed records and their review chains stay byte-for-byte unchanged, and human judgments outrank inference.

## How good is extraction on my documents?

Not yet measured beyond small fixtures and the bundled sample. A local Qwen3.8 model with reasoning off found all 7 decisions in the sample; the one-command demo itself uses mock rules tuned to the sample's text. Measuring recall on more repositories is [up next](../roadmap/).

## Can I expose it to my team over the network?

Not safely. The API and MCP endpoint have no authentication and bind to loopback. Remote access is an open design question.

## Does it analyze source code?

No. Code analysis is a documented extension point with no implementation.

## Can I undo a review?

Yes. The Facts page lists the review log; each entry shows the prior state and an Undo action. Undo appends a record that restores the prior judgment, and is also available through `POST /api/v1/reviews/{record_id}/undo`.

## What does a what-if scenario change?

Nothing in your repository until you save it. Option switches in the What-if panel are temporary previews. A saved scenario stores only its selections under `.decision/scenarios/`.

## Which license applies?

Apache-2.0. The source is at <https://github.com/bcmyguest/switchplinth>.

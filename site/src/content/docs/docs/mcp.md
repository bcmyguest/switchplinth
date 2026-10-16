---
title: MCP tools
description: Five read-only Model Context Protocol tools for listing decisions, searching evidence, inspecting the graph, and diffing scenarios, with input receipts, over HTTP or stdio.
---

The backend serves Model Context Protocol tools, so coding agents and other MCP clients can query the same domain and retrieval services as the UI. Every tool is read-only.

## Transports

| Transport | How to reach it | Notes |
| --- | --- | --- |
| Streamable HTTP | `http://localhost:8000/mcp` while the Compose stack runs | Loopback only, no authentication. Do not expose it. |
| stdio | `switchplinth mcp --repo PATH` | No Docker or Qdrant required. Uses an in-process vector index instead of Qdrant, but still calls a configured embedding model. |

`PATH` is a repository directory with Markdown and `.decision/`; it defaults to the current directory.

Both transports expose the same tools.

## Tools

Every tool except `diff_scenarios` accepts an optional `selections` map from decision ID to option ID. Pass it to ask about a what-if scenario instead of the repository's selected options. Decisions you leave out keep their selected option. Nothing is written.

### `list_decisions`

List every decision with its `id`, `title`, `status`, `selected_option`, and options (`id`, `title`). Call this first to find the IDs that `selections` and the other tools need. `needs_review` is true when extraction rejected an option's deltas and a human must fix them.

| Argument     | Type                 | Required |
| ------------ | -------------------- | -------- |
| `selections` | map of string→string | no       |

### `search_decisions`

Search the repository's Markdown passages and decision claims, for questions such as "Why are we using Kafka?". Returns an extractive `answer`, matching `evidence` passages with source paths, related `claims` and `entities`, and `grounded`.

`grounded` is true only when cited passages support the answer; for questions starting with "why", effective claims must cite the returned passages. Retrieval is lexical plus a vector index, not an LLM answer. Without a configured embedding model, the vector index uses a deterministic local fallback.

| Argument     | Type                 | Required |
| ------------ | -------------------- | -------- |
| `query`      | string               | yes      |
| `selections` | map of string→string | no       |

### `inspect_architecture`

Return the full compiled graph: entities, relationships, decisions with option deltas, aliases, claims, evidence, identity groups, and a `scenario` block with added, removed, and changed records, conflicts, invalid assumptions, and affected decisions. When `selections` differs from the repository's choices, `scenario.impact` lists downstream impact against those choices (see `diff_scenarios`). The response is large; prefer `list_decisions` or `inspect_entity` for targeted questions.

| Argument     | Type                 | Required |
| ------------ | -------------------- | -------- |
| `selections` | map of string→string | no       |

### `inspect_entity`

Return one entity by `entity_id`: its relationships, aliases, claims, cited evidence, related decisions with rationale and all options, and identity groups, suggestions, and conflicts. An unknown ID returns an MCP tool error.

| Argument     | Type                 | Required |
| ------------ | -------------------- | -------- |
| `entity_id`  | string               | yes      |
| `selections` | map of string→string | no       |

### `diff_scenarios`

Compare two scenarios. Each argument is a selection map; an omitted or empty map means the repository-selected options.

| Argument            | Type                 | Required |
| ------------------- | -------------------- | -------- |
| `before_selections` | map of string→string | no       |
| `after_selections`  | map of string→string | no       |

The result holds:

- `selection_changes`: each decision whose option differs, with `before_option` and `after_option`.
- `entities` and `relationships`, each split into `added`, `removed`, and `changed`.
- `conflicts` and `invalid_assumptions`, each split into `appeared` and `disappeared`.
- `affected_decisions`, with the reason each one is affected.
- `impact`: downstream impact, described below.
- `receipt`.

The same comparison is available over HTTP as `POST /api/v1/scenarios/diff` with a `before_selections` / `after_selections` body.

## Downstream impact

For each entity or relationship the after scenario removes or replaces, `impact.items` lists the entities that depend on it. A relationship's source depends on its target, and the walk follows relationships in the before scenario up to `impact.max_depth` hops (4). `truncated: true` means more dependents lie past the cap.

Each dependent carries its `depth` and a `path` of entity and relationship IDs back to the changed item. If one of its outgoing relationships now points at a missing entity, that edge is listed in `missing_endpoints` as either:

- `rewired`: the after scenario gives the same source a relationship of the same kind to a new target, or
- `dangling`: it does not. `points_at_missing` is true when any edge dangles.

In the food-delivery sample, switching event transport from Kafka to SQS removes the Order Service's `publishes_to` edge to the Kafka stream and adds one to the SQS stream, so that edge is `rewired` and nothing dangles.

Impact only sees relationships declared in the graph. It does not read code, runtime traffic, or undeclared dependencies, and it does not follow identity groups. `impact.limits` restates this in every result.

## Receipts

`list_decisions`, `search_decisions`, `inspect_architecture`, and `diff_scenarios` return a `receipt`, as do the matching HTTP reads. It is a digest of the canonical inputs behind the result:

- `records`: every alias, claim, decision, entity, evidence, and relationship file in `.decision/`
- `review_heads`: human judgments that are neither superseded nor undone
- `evidence_anchors`: each anchor's source path, passage hash, and state
- `selections`: the resolved selection map
- `request`: extra inputs, such as the search query

To check whether a result is stale, repeat the same call with the same selections and query, then compare `receipt.digest`. Equal digests mean the canonical inputs have not changed; when they differ, the component hashes show which kind of input changed. The receipt never reads SQLite, Qdrant, or the clock, so an index rebuild or another process gives the same digest.

The receipt does not cover the search index or embedding model, which also affect search ranking, or connections, `config.yaml`, and saved scenarios.

## Example

```json
{
  "query": "Why are we using Kafka?",
  "selections": { "decision-messaging": "option-sqs" }
}
```

## Connecting a client

The setup wizard registers the stdio server for you. From `backend/` in a clone of the repository:

```sh
uv run --locked --python 3.12 switchplinth setup --repo PATH --client claude-code
```

`--client` takes `claude-code`, `claude-desktop`, `cursor`, `vscode`, or `print`. Claude Code is registered through its own `claude mcp add` command (`--claude-scope user|local|project`, default `user`). For the other three, the wizard edits the client's user-level JSON config after showing a diff and asking, and keeps a timestamped backup. `print` writes nothing and prints every snippet. Clients always get the local stdio command, even when the stack runs in Docker. See [Getting started](../getting-started/) for the wizard's other questions.

To configure a client by hand, point it at the stdio command above, or at the streamable HTTP endpoint `http://localhost:8000/mcp` while the Compose stack runs.

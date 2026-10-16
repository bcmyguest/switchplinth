---
title: MCP tools
description: Four read-only Model Context Protocol tools for listing decisions, searching evidence, and inspecting the architecture graph, over HTTP or stdio.
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

Every tool accepts an optional `selections` map from decision ID to option ID. Pass it to ask about a what-if scenario instead of the repository's selected options.

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

Return the full compiled graph: entities, relationships, decisions with option deltas, aliases, claims, evidence, identity groups, and a `scenario` block with added, removed, and changed records, conflicts, invalid assumptions, and affected decisions. The response is large; prefer `list_decisions` or `inspect_entity` for targeted questions.

| Argument     | Type                 | Required |
| ------------ | -------------------- | -------- |
| `selections` | map of string→string | no       |

### `inspect_entity`

Return one entity by `entity_id`: its relationships, aliases, claims, cited evidence, related decisions with rationale and all options, and identity groups, suggestions, and conflicts. An unknown ID returns an MCP tool error.

| Argument     | Type                 | Required |
| ------------ | -------------------- | -------- |
| `entity_id`  | string               | yes      |
| `selections` | map of string→string | no       |

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

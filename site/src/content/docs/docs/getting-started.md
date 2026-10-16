---
title: Getting started
description: Set up a repository and its MCP server with the setup wizard, or run the one-command food-delivery demo in Docker.
---

The app reads the Markdown already in a repository and writes its own portable records to a `.decision/` folder beside it. Everything runs on your machine; no account or cloud service is needed.

There are two ways in:

- **The setup wizard** points it at your repository (or the sample), runs the first scan, and registers the MCP server with your coding agent.
- **The demo script** starts the full web app in Docker on the food-delivery sample.

## Set up with the wizard

You need a clone of the repository, [uv](https://docs.astral.sh/uv/), and Python 3.12. Docker is only needed for Docker mode. From `backend/`:

```sh
uv run --locked --python 3.12 switchplinth setup
```

The wizard asks one question at a time:

1. **Repository:** a path to your repository, or the food-delivery sample.
2. **Mode:** local (the default) opens the repository in-process and needs no Docker. Docker builds and starts the Compose stack with the repository mounted, so you also get the web app.
3. **Model:** none (the default, deterministic mock extraction), an OpenAI-compatible server, OpenAI, or Anthropic. A key is stored only as a reference to an environment variable, such as `credential_ref: env:MY_KEY`, never as the key itself.
4. **First scan** of the repository.
5. **MCP client:** Claude Code, Claude Desktop, Cursor, or VS Code. It can also just print the config snippets and write nothing.
6. **Verify:** it starts the MCP server and checks that it answers.

To skip the questions, answer them with flags. For example, the sample in local mode with defaults for everything else:

```sh
uv run --locked --python 3.12 switchplinth setup --sample --yes
```

| Flag | Answers |
| --- | --- |
| `--repo PATH` or `--sample` | which repository |
| `--mode local` or `--mode docker` | where it runs |
| `--provider none\|openai-compatible\|openai\|anthropic` | model connection, with `--endpoint`, `--model`, `--credential-env NAME`, `--reasoning-off` |
| `--client claude-code\|claude-desktop\|cursor\|vscode\|print` | MCP client to register |
| `--no-scan`, `--no-verify` | skip the first scan or the check |
| `--yes` | take the defaults for every remaining question |

Running it again with the same answers changes nothing. Before it edits a client's JSON config, the wizard shows a diff, asks, and keeps a timestamped backup. On Windows it prints the client snippets instead of writing them, and Docker mode is not available there.

## Try the food-delivery demo

This path needs Docker with Compose v2 and curl, but no model, credentials, Python, or Node. From a clone of the repository:

```sh
./scripts/demo.sh
```

The script:

1. builds the images,
2. copies the fictional food-delivery sample (`fixtures/food-delivery/`) into `~/.cache/switchplinth-demo/food-delivery`,
3. extracts it with deterministic mock extraction,
4. starts the stack as Compose project `switchplinth-demo`,
5. rebuilds the search indexes and prints the URL, `http://localhost:3000`.

The sample holds nine Markdown files (design notes, RFCs, decision notes) for a fictional ordering, payment, restaurant, and courier workflow. They yield 7 decisions; the default scenario has 18 entities and 13 relationships. Switching the event-transport decision from Kafka to SQS moves the order event stream edge.

:::caution[What the sample shows]
The mock extractor's phrase rules are written for this sample's text. The sample demonstrates the decision, evidence, map, and what-if model. It says nothing about extraction quality on your own documents.
:::

| Command | Effect |
| --- | --- |
| `./scripts/demo.sh --down` | Stop the demo stack and delete its volumes. Keeps the workspace. |
| `./scripts/demo.sh --reset` | Delete the demo sample and bootstrap it again. |
| `./scripts/demo.sh --purge` | Stop the stack, delete its volumes, and delete the demo workspace. |

The backend container runs as root, so after you scan or review in the UI the workspace holds root-owned files. Remove it with `--purge`, not `rm`.

Optional environment variables:

- `DECISION_DEMO_WORKSPACE` chooses another workspace directory.
- `DECISION_FRONTEND_PORT`, `DECISION_BACKEND_PORT`, and `DECISION_QDRANT_PORT` replace ports 3000, 8000, and 6333 when they are taken. Stop any other stack on those ports first.

The sidebar shows the repository name `repos` because the sample is mounted at `/workspace/repos`.

## Run the web app on your own repository

```sh
DECISION_WORKSPACE_HOST=/path/to/your/workspace docker compose up --build
```

Compose mounts `${DECISION_WORKSPACE_HOST:-.}` at `/workspace/repos`; without the variable, that is the directory where you ran Compose. Compose starts three separate services:

| Service  | Address                      |
| -------- | ---------------------------- |
| Web app  | `http://localhost:3000`      |
| API docs | `http://localhost:8000/docs` |
| Qdrant   | `http://localhost:6333`      |

All published ports bind to `127.0.0.1`. The API and MCP endpoint are unauthenticated, so keep them on loopback.

The repository chooser lists directories under the mount that contain Markdown, `.git`, or `.decision`. It accepts only relative paths and rejects symlink traversal. The first time you open a Markdown-only repository, the app writes a `.decision/` folder with the v1 schema, a config file, and extraction instructions. It does not impose an ADR template or modify your Markdown.

## Discover decisions

Choose **Discover** and pick an extraction mode:

- **Deterministic/mock** needs no model.
- **Provider** uses a configured model connection. See [Model providers](../providers/).

Extraction writes inferred records with evidence anchors to `.decision/`, then rebuilds the SQLite and Qdrant indexes from the canonical files.

## Reset generated state

SQLite lives in the `decision-cache` volume and Qdrant data in `qdrant-data`. Both rebuild from the repository:

```sh
docker compose down -v
```

This removes the generated volumes only. Your Markdown and `.decision/` files stay in place.

## Next

- [Concepts](../concepts/): decisions, options, deltas, scenarios, claims, evidence.
- [MCP tools](../mcp/): query decisions from a coding agent.
- [Up next](../roadmap/): what works today and the next steps.

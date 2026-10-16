# Switchplinth backend

FastAPI service and portable-data compiler for Switchplinth, packaged as `switchplinth` (import `switchplinth`, CLI `switchplinth`). Python 3.12 is the supported runtime.

Run tests with `uv run --python 3.12 pytest -q`. The service uses `DECISION_REPO` for the repository containing Markdown and `.decision/`, `DECISION_CACHE` for disposable SQLite state, and `QDRANT_URL` for the derived vector index. Compose mounts the host workspace at `/workspace/repos`.

The API is served on port 8000. Open `/docs` for the OpenAPI interface. MCP is exposed at `/mcp`; `switchplinth mcp --repo PATH` serves the same tools over stdio.

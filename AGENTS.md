# Repository guidance

## Engineering rules

- Treat Markdown sources and validated, versioned YAML under `.decision/` as the only canonical knowledge. SQLite, Qdrant, embeddings, workflow state, and generated graph data are disposable.
- Keep deterministic domain and compiler logic independent of storage, UI, and model providers. Model output is an inference; confirmed, rejected, or overridden human records take precedence.
- Preserve provenance for inferred claims and aliases. Use relocatable content/structure anchors, never line numbers as identity.
- Model options as typed operations over a base graph. YAML, graph editing, and conversation must write the same delta model.
- Validate portable YAML against versioned schemas and make migrations explicit. Rebuild generated state from canonical files.
- Keep `frontend`, `backend`, and `qdrant` as distinct Compose services. Do not add Postgres, Redis, Neo4j, or another canonical database in V0.
- Keep provider configuration behind the product's provider-neutral contract; LiteLLM is an implementation detail. Keep inference model connections separate from coding-agent connections.
- Keep code-analysis extraction out of V0; leave a documented extension point with distinct code-derived evidence types.
- Add function and class definitions after constants in each source file. Keep changes small, inspectable, and documented in `README.md` and `CLAUDE.md` when setup or behavior changes.

## Commands

Install and run the service checks with the repository's pinned tools:

```sh
docker compose up --build
docker compose down
docker compose down -v                 # deletes disposable service volumes
cd backend && uv run --locked --python 3.12 pytest -q
cd frontend && pnpm install --frozen-lockfile
cd frontend && pnpm typecheck && pnpm lint && pnpm build
```

Run service-specific checks from the service directory and report the exact command and result. In environments where pnpm cannot open its package store, run the installed binaries directly: `./node_modules/.bin/tsc -b`, `./node_modules/.bin/eslint .`, and `./node_modules/.bin/vite build` from `frontend/`. Do not claim a command works until the files and dependencies exist and it has been run.

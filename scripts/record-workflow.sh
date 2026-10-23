#!/usr/bin/env bash
# Record docs/assets/workflow.gif with real model extraction: write an ADR, run Discover through a local
# OpenAI-compatible model server (Lemonade by default), read the decision in the Architecture log, find it on the map,
# preview its alternative in What-if, ask why in Explore, and ask the model to change the alternative.
#
# It copies the food-delivery sample's Markdown, with no prior extraction, into a temporary directory, starts the
# backend and the frontend dev server on loopback, registers the model connection, and runs
# site/scripts/workflow-gif.mjs. Nothing outside the temporary directory changes except the output GIF.
# Requires uv, pnpm, curl, and a running model server. No Docker or Qdrant: search falls back to the local index.
#
# Usage: LEMONADE_MODEL=Qwen3-8B-GGUF scripts/record-workflow.sh [output.gif]
#
# Environment:
#   LEMONADE_MODEL         model name as the server lists it (required)
#   LEMONADE_BASE_URL      OpenAI-compatible base URL (default: http://localhost:8000/api/v1, Lemonade's default)
#   LEMONADE_TIMEOUT       per-request timeout in seconds (default: 1800; CPU-only models are slow)
#   WORKFLOW_BACKEND_PORT  backend port (default: 8765)
#   WORKFLOW_FRONTEND_PORT frontend port (default: 5199)
#   PLAYWRIGHT_CHROMIUM    an installed Chromium to use instead of running `playwright install chromium`
#   WORKFLOW_KEEP=1        keep the temporary repository and logs for inspection
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="$(realpath -m "${1:-$REPO_ROOT/docs/assets/workflow.gif}")"
MODEL="${LEMONADE_MODEL:?Set LEMONADE_MODEL to the model name your server lists, for example Qwen3-8B-GGUF}"
BASE_URL="${LEMONADE_BASE_URL:-http://localhost:8000/api/v1}"
TIMEOUT="${LEMONADE_TIMEOUT:-1800}"
BACKEND_PORT="${WORKFLOW_BACKEND_PORT:-8765}"
FRONTEND_PORT="${WORKFLOW_FRONTEND_PORT:-5199}"
CONNECTION_ID="workflow-recording"
WORK="$(mktemp -d)"
SAMPLE="$WORK/food-delivery"
PIDS=()

cleanup() {
  for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
  if [[ "${WORKFLOW_KEEP:-}" == 1 ]]; then echo "Kept $WORK (backend.log, frontend.log, food-delivery/)"; else rm -rf "$WORK"; fi
}
trap cleanup EXIT

wait_for() {
  local url="$1" name="$2"
  for _ in $(seq 1 120); do
    if curl -fs -o /dev/null "$url"; then return 0; fi
    sleep 1
  done
  echo "$name did not answer at $url; see $WORK/${name}.log" >&2
  WORKFLOW_KEEP=1
  exit 1
}

echo "Checking the model server at $BASE_URL"
if ! curl -fsS "$BASE_URL/models" | grep -q "\"$MODEL\""; then
  echo "The server at $BASE_URL/models does not list \"$MODEL\". Start Lemonade and load the model, or set LEMONADE_BASE_URL." >&2
  exit 1
fi

echo "Copying the sample Markdown to $SAMPLE (no extraction)"
mkdir -p "$SAMPLE"
cp -R "$REPO_ROOT/fixtures/food-delivery/docs/." "$SAMPLE/"

echo "Starting the backend on 127.0.0.1:$BACKEND_PORT"
(cd "$REPO_ROOT/backend" && uv sync --locked --python 3.12 --quiet)
(
  cd "$REPO_ROOT/backend"
  export DECISION_REPO="$SAMPLE" DECISION_WORKSPACE_ROOT="$WORK" DECISION_WORKSPACE_NAME=food-delivery DECISION_CACHE="$WORK/cache" QDRANT_URL="http://127.0.0.1:9"
  exec uv run --locked --python 3.12 uvicorn switchplinth.api:app --host 127.0.0.1 --port "$BACKEND_PORT"
) >"$WORK/backend.log" 2>&1 &
PIDS+=($!)
wait_for "http://127.0.0.1:$BACKEND_PORT/api/v1/project" backend

echo "Registering model connection $CONNECTION_ID ($MODEL)"
curl -fsS -X POST "http://127.0.0.1:$BACKEND_PORT/api/v1/connections" -H 'content-type: application/json' \
  -d "{\"id\":\"$CONNECTION_ID\",\"name\":\"Lemonade\",\"provider\":\"openai_compatible\",\"endpoint\":\"$BASE_URL\",\"model\":\"$MODEL\",\"capabilities\":{\"structured_output\":true},\"generation\":{\"reasoning\":\"off\",\"request_timeout_seconds\":$TIMEOUT}}" >/dev/null

echo "Starting the frontend on 127.0.0.1:$FRONTEND_PORT"
(cd "$REPO_ROOT/frontend" && pnpm install --frozen-lockfile --silent)
(
  cd "$REPO_ROOT/frontend"
  export DECISION_BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
  exec ./node_modules/.bin/vite --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
) >"$WORK/frontend.log" 2>&1 &
PIDS+=($!)
wait_for "http://127.0.0.1:$FRONTEND_PORT/" frontend

(cd "$REPO_ROOT/site" && pnpm install --frozen-lockfile --silent)
if [[ -z "${PLAYWRIGHT_CHROMIUM:-}" ]]; then (cd "$REPO_ROOT/site" && pnpm exec playwright install chromium); fi

echo "Recording; extraction runs on the model, so this can take a while"
(cd "$REPO_ROOT/site" && WORKFLOW_CONNECTION="$CONNECTION_ID" node scripts/workflow-gif.mjs "http://127.0.0.1:$FRONTEND_PORT/" "$SAMPLE" "$OUTPUT")
echo "Wrote $OUTPUT"

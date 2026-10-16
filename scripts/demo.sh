#!/usr/bin/env bash
# Start a disposable food-delivery demo: bootstrap the sample corpus with
# deterministic mock extraction, start the Compose stack on it, and rebuild
# the search indexes. Requires Docker with Compose v2 and curl; no model,
# credentials, Python, or Node on the host.
#
# Usage: scripts/demo.sh [--reset | --down | --purge]
#   --reset  delete the demo sample and bootstrap it again
#   --down   stop the demo stack and delete its volumes (keeps the workspace)
#   --purge  stop the stack, delete its volumes, and delete the demo workspace
#
# Environment (all optional):
#   DECISION_DEMO_WORKSPACE  host directory for the sample repository
#                            (default: ${XDG_CACHE_HOME:-$HOME/.cache}/switchplinth-demo)
#   COMPOSE_PROJECT_NAME     Compose project (default: switchplinth-demo)
#   DECISION_FRONTEND_PORT, DECISION_BACKEND_PORT, DECISION_QDRANT_PORT
#                            loopback ports (defaults: 3000, 8000, 6333)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="${DECISION_DEMO_WORKSPACE:-${XDG_CACHE_HOME:-$HOME/.cache}/switchplinth-demo}"
SAMPLE="$WORKSPACE/food-delivery"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-switchplinth-demo}"
export DECISION_WORKSPACE_HOST="$SAMPLE"
export DECISION_WORKSPACE_NAME="${SAMPLE##*/}"
FRONTEND_PORT="${DECISION_FRONTEND_PORT:-3000}"
BACKEND_PORT="${DECISION_BACKEND_PORT:-8000}"

compose() { docker compose --project-directory "$REPO_ROOT" -f "$REPO_ROOT/docker-compose.yml" "$@"; }

# Run a command in the backend image without starting Qdrant. The workspace
# parent is mounted at /work so the bootstrap can create the sample directory.
backend_run() {
  compose run --rm --no-deps --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$REPO_ROOT/fixtures:/fixtures:ro" -v "$WORKSPACE:/work" "$@"
}

# Delete everything inside the workspace as root: scans run as root inside the
# backend container and leave root-owned files. The workspace itself is the
# Compose mount here, so the sample directory is not a live bind source.
clean_workspace() {
  [ -d "$WORKSPACE" ] || return 0
  DECISION_WORKSPACE_HOST="$WORKSPACE" compose run --rm --no-deps -v "$WORKSPACE:/work" backend \
    sh -c 'find /work -mindepth 1 -maxdepth 1 -exec rm -rf {} +'
}

command -v docker >/dev/null || { echo "Docker is required: install Docker with Compose v2 (https://docs.docker.com/get-docker/)." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required (the 'docker compose' command)." >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required." >&2; exit 1; }

case "${1:-}" in
  --down)
    compose down -v
    exit 0
    ;;
  --purge)
    compose down -v
    clean_workspace
    # The cleanup container recreates the project's network and volumes.
    compose down -v >/dev/null 2>&1
    rmdir "$WORKSPACE" 2>/dev/null || true
    echo "Removed the demo stack, its volumes, and $WORKSPACE."
    exit 0
    ;;
  --reset)
    compose down -v
    clean_workspace
    ;;
  "") ;;
  *)
    echo "Usage: $0 [--reset | --down | --purge]" >&2
    exit 2
    ;;
esac

# Create the sample directory as the current user; otherwise Docker creates
# the bind-mount source as root and the bootstrap cannot write into it.
mkdir -p "$SAMPLE"
echo "Building images (first run takes a few minutes)..."
compose build

if [ -d "$SAMPLE/.decision" ]; then
  echo "Reusing existing sample at $SAMPLE (run with --reset to recreate it)."
else
  echo "Bootstrapping the food-delivery sample into $SAMPLE ..."
  backend_run backend /app/.venv/bin/python /fixtures/food-delivery/bootstrap.py /work/food-delivery
fi

echo "Starting the stack (project $COMPOSE_PROJECT_NAME)..."
compose up -d --wait --wait-timeout 180

# The bootstrap wrote its indexes outside the stack. A deterministic rescan
# rebuilds SQLite and Qdrant inside the running backend.
echo "Rebuilding search indexes..."
if ! curl -fsS -X POST "http://127.0.0.1:$BACKEND_PORT/api/v1/discovery/scan" -o /dev/null; then
  echo "Index rebuild failed: POST http://127.0.0.1:$BACKEND_PORT/api/v1/discovery/scan did not succeed." >&2
  echo "Check the backend logs: docker compose -p $COMPOSE_PROJECT_NAME logs backend" >&2
  exit 1
fi

decisions="$(compose exec -T backend python -c 'import json, urllib.request; print(len(json.load(urllib.request.urlopen("http://localhost:8000/api/v1/decisions"))))')"
cat <<EOF

Demo ready: $decisions decisions loaded from the food-delivery sample.
  Web app:  http://localhost:$FRONTEND_PORT
  API docs: http://localhost:$BACKEND_PORT/docs
Stop it with: $0 --down
EOF

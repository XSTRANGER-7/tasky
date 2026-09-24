#!/usr/bin/env bash
# Block until the API's /health returns 200 (used by CI after `docker compose up`).
#   scripts/wait-for-health.sh [url] [timeout-seconds]
set -euo pipefail

URL="${1:-http://localhost:8000/health}"
TIMEOUT="${2:-120}"
deadline=$(( $(date +%s) + TIMEOUT ))

until body=$(curl -fsS "$URL" 2>/dev/null); do
  if (( $(date +%s) >= deadline )); then
    echo "timed out after ${TIMEOUT}s waiting for $URL" >&2
    docker compose ps >&2 || true
    docker compose logs --tail=80 api >&2 || true
    exit 1
  fi
  sleep 2
done

echo "healthy: $body"

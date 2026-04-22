#!/usr/bin/env bash
set -euo pipefail

SERVICE="${1:-}"
if [ -z "$SERVICE" ]; then
  echo "Usage: ./scripts/rebuild-service.sh <service>"
  exit 1
fi

docker compose rm -sf "$SERVICE" 2>/dev/null || true
docker compose -f docker-compose.ai.yml rm -sf "$SERVICE" 2>/dev/null || true
docker compose -f docker-compose.ops.yml rm -sf "$SERVICE" 2>/dev/null || true
docker compose -f docker-compose.automation.yml rm -sf "$SERVICE" 2>/dev/null || true

docker compose up -d "$SERVICE" 2>/dev/null || true
docker compose -f docker-compose.ai.yml up -d "$SERVICE" 2>/dev/null || true
docker compose -f docker-compose.ops.yml up -d "$SERVICE" 2>/dev/null || true
docker compose -f docker-compose.automation.yml up -d "$SERVICE" 2>/dev/null || true
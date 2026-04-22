#!/usr/bin/env bash
set -euo pipefail

SERVICE="${1:-}"
LINES="${2:-80}"

if [ -n "$SERVICE" ]; then
  docker compose logs --tail="$LINES" "$SERVICE" || \
  docker compose -f docker-compose.ai.yml logs --tail="$LINES" "$SERVICE" || \
  docker compose -f docker-compose.ops.yml logs --tail="$LINES" "$SERVICE" || \
  docker compose -f docker-compose.automation.yml logs --tail="$LINES" "$SERVICE"
else
  docker ps
fi
#!/usr/bin/env bash
set -euo pipefail
docker compose pull || true
docker compose -f docker-compose.ai.yml pull || true
docker compose -f docker-compose.ops.yml pull || true
docker compose -f docker-compose.automation.yml pull || true
./scripts/up.sh
docker image prune -f
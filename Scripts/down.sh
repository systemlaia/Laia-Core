#!/usr/bin/env bash
set -euo pipefail
docker compose -f docker-compose.ai.yml down || true
docker compose -f docker-compose.ops.yml down || true
docker compose -f docker-compose.automation.yml down || true
docker compose down || true
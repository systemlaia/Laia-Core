#!/usr/bin/env bash
set -euo pipefail
docker compose up -d
docker compose -f docker-compose.ai.yml up -d
docker compose -f docker-compose.ops.yml up -d
docker compose -f docker-compose.automation.yml up -d
docker ps
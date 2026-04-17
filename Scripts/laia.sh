#!/usr/bin/env bash
set -euo pipefail

cmd="${1:-help}"

case "$cmd" in
  up)
    ./scripts/up.sh
    ;;
  down)
    ./scripts/down.sh
    ;;
  restart)
    ./scripts/down.sh
    ./scripts/up.sh
    ;;
  ps)
    docker ps
    ;;
  logs)
    shift || true
    if [ "$#" -gt 0 ]; then
      docker compose logs -f "$@" || \
      docker compose -f docker-compose.ai.yml logs -f "$@" || \
      docker compose -f docker-compose.ops.yml logs -f "$@" || \
      docker compose -f docker-compose.automation.yml logs -f "$@"
    else
      docker ps
    fi
    ;;
  config)
    docker compose config >/dev/null
    docker compose -f docker-compose.ai.yml config >/dev/null
    docker compose -f docker-compose.ops.yml config >/dev/null
    docker compose -f docker-compose.automation.yml config >/dev/null
    echo "All compose files validated."
    ;;
  help|*)
    echo "Usage: ./scripts/laia.sh {up|down|restart|ps|logs [service]|config}"
    ;;
esac
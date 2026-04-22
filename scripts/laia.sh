#!/usr/bin/env bash
set -euo pipefail

cmd="${1:-help}"
service="${2:-}"

ai_services=("ollama" "open-webui")
ops_services=("homepage" "filebrowser" "portainer")
automation_services=("postgres" "redis" "n8n")

in_list() {
  local item="$1"
  shift
  for x in "$@"; do
    [[ "$x" == "$item" ]] && return 0
  done
  return 1
}

service_compose() {
  local svc="$1"
  if in_list "$svc" "${ai_services[@]}"; then
    echo "docker-compose.ai.yml"
  elif in_list "$svc" "${ops_services[@]}"; then
    echo "docker-compose.ops.yml"
  elif in_list "$svc" "${automation_services[@]}"; then
    echo "docker-compose.automation.yml"
  else
    echo ""
  fi
}

case "$cmd" in
  up)
    docker compose up -d
    docker compose -f docker-compose.ai.yml up -d
    docker compose -f docker-compose.ops.yml up -d
    docker compose -f docker-compose.automation.yml up -d
    ;;
  down)
    docker compose -f docker-compose.ai.yml down || true
    docker compose -f docker-compose.ops.yml down || true
    docker compose -f docker-compose.automation.yml down || true
    docker compose down || true
    ;;
  restart)
    if [[ -n "$service" ]]; then
      file="$(service_compose "$service")"
      if [[ -z "$file" ]]; then
        echo "Unknown service: $service"
        exit 1
      fi
      docker compose -f "$file" restart "$service"
    else
      "$0" down
      "$0" up
    fi
    ;;
  ps)
    docker ps
    ;;
  logs)
    if [[ -n "$service" ]]; then
      file="$(service_compose "$service")"
      if [[ -z "$file" ]]; then
        echo "Unknown service: $service"
        exit 1
      fi
      docker compose -f "$file" logs --tail=100 "$service"
    else
      docker ps
    fi
    ;;
  follow)
    if [[ -n "$service" ]]; then
      file="$(service_compose "$service")"
      if [[ -z "$file" ]]; then
        echo "Unknown service: $service"
        exit 1
      fi
      docker compose -f "$file" logs -f "$service"
    else
      echo "Usage: ./scripts/laia.sh follow <service>"
      exit 1
    fi
    ;;
  rebuild)
    if [[ -z "$service" ]]; then
      echo "Usage: ./scripts/laia.sh rebuild <service>"
      exit 1
    fi
    file="$(service_compose "$service")"
    if [[ -z "$file" ]]; then
      echo "Unknown service: $service"
      exit 1
    fi
    docker compose -f "$file" rm -sf "$service" || true
    docker compose -f "$file" up -d "$service"
    ;;
  config)
    docker compose config >/dev/null
    docker compose -f docker-compose.ai.yml config >/dev/null
    docker compose -f docker-compose.ops.yml config >/dev/null
    docker compose -f docker-compose.automation.yml config >/dev/null
    echo "All compose files validated."
    ;;
  help|*)
    echo "Usage: ./scripts/laia.sh {up|down|restart [service]|ps|logs [service]|follow <service>|rebuild <service>|config}"
    ;;
esac
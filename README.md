# LAIA Core

LAIA Core is a modular local infrastructure stack for AI, automation, operations, and archive access.

## Services

- Homepage: http://localhost:4000
- Open WebUI: http://localhost:3000
- Filebrowser: http://localhost:8080
- n8n: http://localhost:5678
- Portainer: https://localhost:9443
- Ollama API: http://localhost:11434

## Compose Layout

- `docker-compose.yml` — foundation
- `docker-compose.ai.yml` — AI layer
- `docker-compose.ops.yml` — ops layer
- `docker-compose.automation.yml` — automation layer

## Operator Commands

```bash
./scripts/laia.sh up
./scripts/laia.sh down
./scripts/laia.sh restart
./scripts/laia.sh ps
./scripts/laia.sh logs
./scripts/laia.sh config
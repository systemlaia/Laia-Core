#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-$HOME/LAIA-Core}"

mkdir -p "$TARGET_DIR"
cd "$TARGET_DIR"

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "Created .env from .env.example — edit secrets before external deployment."
fi

mkdir -p caddy/data caddy/config
mkdir -p filebrowser
mkdir -p homepage/config
mkdir -p ollama/data open-webui/data portainer/data postgres/data redis/data n8n/data
mkdir -p archive/ingest archive/projects archive/nas

chmod +x scripts/*.sh 2>/dev/null || true

./scripts/laia.sh config
./scripts/laia.sh up

echo
echo "Deployment complete."
echo "Homepage   : http://localhost:4000"
echo "Open WebUI : http://localhost:3000"
echo "Filebrowser: http://localhost:8080"
echo "n8n        : http://localhost:5678"
echo "Portainer  : https://localhost:9443"
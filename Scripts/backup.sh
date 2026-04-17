#!/usr/bin/env bash
set -euo pipefail

STAMP="$(date +%Y-%m-%d_%H-%M-%S)"
BACKUP_DIR="${BACKUP_DIR:-./backups/$STAMP}"
mkdir -p "$BACKUP_DIR"
mkdir -p "$BACKUP_DIR/postgres"
mkdir -p "$BACKUP_DIR/config"

cp -R ./caddy "$BACKUP_DIR/config/" 2>/dev/null || true
cp -R ./homepage "$BACKUP_DIR/config/" 2>/dev/null || true
cp -R ./scripts "$BACKUP_DIR/config/" 2>/dev/null || true
cp ./docker-compose.yml "$BACKUP_DIR/config/" 2>/dev/null || true
cp ./docker-compose.ai.yml "$BACKUP_DIR/config/" 2>/dev/null || true
cp ./docker-compose.ops.yml "$BACKUP_DIR/config/" 2>/dev/null || true
cp ./docker-compose.automation.yml "$BACKUP_DIR/config/" 2>/dev/null || true
cp ./README.md "$BACKUP_DIR/config/" 2>/dev/null || true
cp ./.env "$BACKUP_DIR/config/.env.backup" 2>/dev/null || true

if docker ps --format '{{.Names}}' | grep -q '^laia-postgres$'; then
  docker exec laia-postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > "$BACKUP_DIR/postgres/${POSTGRES_DB}.sql"
fi
tar -czf "$BACKUP_DIR/runtime-data.tgz" \
  ./open-webui/data \
  ./portainer/data \
  ./filebrowser \
  ./n8n/data \
  ./postgres/data \
  ./redis/data \
  ./paperless 2>/dev/null || true

echo "Backup created at: $BACKUP_DIR"
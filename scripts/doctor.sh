#!/usr/bin/env bash
set -euo pipefail

echo "== Docker =="
docker version >/dev/null && echo "Docker CLI and daemon reachable"
docker info >/dev/null && echo "Docker info OK"

echo
 echo "== Compose files =="
./scripts/laia.sh config

echo
 echo "== Containers =="
docker ps --format 'table {{.Names}}	{{.Image}}	{{.Status}}'

echo
 echo "== Disk usage =="
docker system df || true

echo
 echo "== Core endpoints =="
./scripts/check.sh
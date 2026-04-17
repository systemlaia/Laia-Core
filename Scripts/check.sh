#!/usr/bin/env bash
set -euo pipefail

echo "== Compose validation =="
./scripts/laia.sh config

echo
 echo "== Container status =="
docker ps --format 'table {{.Names}}	{{.Status}}	{{.Ports}}'

echo
 echo "== HTTP checks =="
curl -s -o /dev/null -w 'Open WebUI  : %{http_code}
' http://localhost:3000 || true
curl -s -o /dev/null -w 'Homepage    : %{http_code}
' http://localhost:4000 || true
curl -s -o /dev/null -w 'Filebrowser : %{http_code}
' http://localhost:8080 || true
curl -s -o /dev/null -w 'n8n         : %{http_code}
' http://localhost:5678 || true
curl -k -s -o /dev/null -w 'Portainer   : %{http_code}
' https://localhost:9443 || true
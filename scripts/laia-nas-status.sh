#!/usr/bin/env bash
set -euo pipefail

NAS="$HOME/NAS/Public"

echo "== LAIA NAS STATUS =="

if mount | grep -q "$NAS"; then
  echo "✅ NAS mounted: $NAS"
else
  echo "❌ NAS not mounted: $NAS"
  exit 1
fi

df -h "$NAS"

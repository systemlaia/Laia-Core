#!/usr/bin/env bash
set -euo pipefail

ROOT="/Volumes/Public/LAIA/packets/photo_ingest"

LAST_PACKET="$(find "$ROOT" -mindepth 2 -maxdepth 2 -type d | sort | tail -n 1)"

if [[ -z "$LAST_PACKET" ]]; then
  echo "No photo ingest packets found."
  exit 1
fi

echo "Latest packet:"
echo "$LAST_PACKET"
echo

"$HOME/LAIA/photo_ingest/bin/laia_photo_verify_packet.sh" "$LAST_PACKET"

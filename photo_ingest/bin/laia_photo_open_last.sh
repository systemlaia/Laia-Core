#!/usr/bin/env bash
set -euo pipefail

ROOT="/Volumes/Public/LAIA/packets/photo_ingest"

LAST_PACKET="$(find "$ROOT" -mindepth 2 -maxdepth 2 -type d | sort | tail -n 1)"

if [[ -z "$LAST_PACKET" ]]; then
  echo "No photo ingest packets found."
  exit 1
fi

echo "Opening:"
echo "$LAST_PACKET"

open "$LAST_PACKET"

if [[ -f "$LAST_PACKET/contact_sheet/contact_sheet.jpg" ]]; then
  open "$LAST_PACKET/contact_sheet/contact_sheet.jpg"
fi

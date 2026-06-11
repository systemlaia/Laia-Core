#!/usr/bin/env bash
set -euo pipefail

PACKET="${1:-}"

if [[ -z "$PACKET" ]]; then
  echo "Usage: laia_photo_verify_packet.sh /path/to/photo_packet"
  exit 1
fi

if [[ ! -d "$PACKET" ]]; then
  echo "Packet folder not found: $PACKET"
  exit 1
fi

echo "Verifying LAIA photo packet:"
echo "$PACKET"
echo

REQUIRED=(
  "originals"
  "previews"
  "metadata"
  "contact_sheet"
  "logs"
  "checksums.sha256"
  "packet_manifest.json"
  "ingest_report.md"
)

FAIL=0

for ITEM in "${REQUIRED[@]}"; do
  if [[ ! -e "$PACKET/$ITEM" ]]; then
    echo "MISSING: $ITEM"
    FAIL=1
  else
    echo "OK: $ITEM"
  fi
done

echo
echo "Counting files..."

ORIGINAL_COUNT="$(find "$PACKET/originals" -type f | wc -l | tr -d ' ')"
CHECKSUM_COUNT="$(wc -l < "$PACKET/checksums.sha256" | tr -d ' ')"
PREVIEW_COUNT="$(find "$PACKET/previews" -type f -iname "*.jpg" | wc -l | tr -d ' ')"

echo "Originals: $ORIGINAL_COUNT"
echo "Checksums: $CHECKSUM_COUNT"
echo "Previews: $PREVIEW_COUNT"

if [[ "$ORIGINAL_COUNT" != "$CHECKSUM_COUNT" ]]; then
  echo "WARNING: original count and checksum count do not match"
  FAIL=1
fi

if [[ ! -f "$PACKET/contact_sheet/contact_sheet.jpg" ]]; then
  echo "WARNING: contact_sheet.jpg missing"
  FAIL=1
else
  echo "OK: contact_sheet.jpg"
fi

echo
echo "Running checksum verification..."
(
  cd "$PACKET/originals"
  shasum -a 256 -c "$PACKET/checksums.sha256"
)

echo
if [[ "$FAIL" -eq 0 ]]; then
  echo "PACKET VERIFIED"
else
  echo "PACKET HAS WARNINGS OR ERRORS"
  exit 2
fi

#!/usr/bin/env bash
set -euo pipefail

ROOT="/Volumes/Public/LAIA/packets/photo_ingest"
INDEX="$ROOT/photo_ingest_index.csv"

mkdir -p "$ROOT"

echo "job_id,packet_path,source,photo_count,packet_size,created_at" > "$INDEX"

find "$ROOT" -mindepth 2 -maxdepth 2 -type d | sort | while read -r PACKET; do
  MANIFEST="$PACKET/packet_manifest.json"
  if [[ -f "$MANIFEST" ]]; then
    python3 - "$MANIFEST" "$PACKET" >> "$INDEX" <<'PY'
import json, sys, csv

manifest_path = sys.argv[1]
packet_path = sys.argv[2]

with open(manifest_path, "r") as f:
    data = json.load(f)

row = [
    data.get("job_id", ""),
    data.get("packet_path", packet_path),
    data.get("source", ""),
    data.get("photo_count", ""),
    data.get("packet_size", ""),
    data.get("created_at", ""),
]

writer = csv.writer(sys.stdout)
writer.writerow(row)
PY
  fi
done

echo "Index written:"
echo "$INDEX"

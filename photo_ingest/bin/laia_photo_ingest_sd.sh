#!/usr/bin/env bash
set -euo pipefail

SRC="${1:-}"

if [[ -z "$SRC" ]]; then
  echo "Usage: laia_photo_ingest_sd.sh /Volumes/CARDNAME/DCIM"
  exit 1
fi

if [[ ! -d "$SRC" ]]; then
  echo "Source folder not found: $SRC"
  exit 1
fi

ROOT_LOCAL="$HOME/LAIA/photo_ingest"
ROOT_NAS="/Volumes/Public/LAIA/packets/photo_ingest"
YEAR="$(date +"%Y")"
STAMP="$(date +"%Y%m%d-%H%M%S")"
CARD_NAME="$(basename "$(dirname "$SRC")")"
SAFE_CARD_NAME="$(echo "$CARD_NAME" | tr ' /:' '___' | tr -cd '[:alnum:]_.-')"
JOB_ID="${STAMP}_${SAFE_CARD_NAME}_sd_ingest"

PACKET="$ROOT_NAS/$YEAR/$JOB_ID"
LOG="$ROOT_LOCAL/logs/$JOB_ID.log"

mkdir -p "$PACKET"/{originals,previews,metadata,contact_sheet,logs}
mkdir -p "$ROOT_LOCAL/logs"

echo "LAIA Photo SD Ingest Job: $JOB_ID" | tee "$LOG"
echo "Source: $SRC" | tee -a "$LOG"
echo "Packet: $PACKET" | tee -a "$LOG"
echo "Started: $(date)" | tee -a "$LOG"

echo "Copying originals to NAS packet..." | tee -a "$LOG"
rsync -avh --progress \
  --include='*/' \
  --include='*.JPG' --include='*.jpg' \
  --include='*.JPEG' --include='*.jpeg' \
  --include='*.RAF' --include='*.raf' \
  --include='*.RAW' --include='*.raw' \
  --include='*.DNG' --include='*.dng' \
  --include='*.TIF' --include='*.tif' \
  --include='*.TIFF' --include='*.tiff' \
  --include='*.PNG' --include='*.png' \
  --exclude='*' \
  "$SRC"/ "$PACKET/originals"/ | tee -a "$LOG"

echo "Generating checksums..." | tee -a "$LOG"
(
  cd "$PACKET/originals"
  find . -type f -print0 | sort -z | xargs -0 shasum -a 256
) > "$PACKET/checksums.sha256"

echo "Generating EXIF metadata..." | tee -a "$LOG"
if command -v exiftool >/dev/null 2>&1; then
  exiftool -json -r "$PACKET/originals" > "$PACKET/metadata/exiftool.json"
  exiftool -csv -r "$PACKET/originals" > "$PACKET/metadata/exiftool.csv"
else
  echo "exiftool not found; skipping EXIF extraction" | tee -a "$LOG"
fi

echo "Generating JPEG previews..." | tee -a "$LOG"
if command -v magick >/dev/null 2>&1; then
  find "$PACKET/originals" -type f \( \
    -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.tif" -o -iname "*.tiff" \
  \) -print0 | while IFS= read -r -d '' IMG; do
    REL="${IMG#$PACKET/originals/}"
    OUT="$PACKET/previews/${REL%.*}.jpg"
    mkdir -p "$(dirname "$OUT")"
    magick "$IMG" -auto-orient -resize 1600x1600\> -quality 85 "$OUT" || true
  done
else
  echo "ImageMagick not found; skipping previews" | tee -a "$LOG"
fi

echo "Creating contact sheet..." | tee -a "$LOG"
if command -v magick >/dev/null 2>&1; then
  find "$PACKET/previews" -type f -iname "*.jpg" | sort | head -n 60 > "$PACKET/contact_sheet/contact_sheet_files.txt"
  if [[ -s "$PACKET/contact_sheet/contact_sheet_files.txt" ]]; then
    magick montage @"$PACKET/contact_sheet/contact_sheet_files.txt" \
      -thumbnail 240x240 \
      -background white \
      -gravity center \
      -extent 240x240 \
      -tile 5x \
      -geometry +8+8 \
      "$PACKET/contact_sheet/contact_sheet.jpg" || true
  fi
fi

PHOTO_COUNT="$(find "$PACKET/originals" -type f | wc -l | tr -d ' ')"
PACKET_SIZE="$(du -sh "$PACKET" | awk '{print $1}')"

cat > "$PACKET/packet_manifest.json" <<MANIFEST
{
  "packet_type": "laia.photo_ingest",
  "packet_version": "0.1",
  "job_id": "$JOB_ID",
  "source": "$SRC",
  "packet_path": "$PACKET",
  "photo_count": "$PHOTO_COUNT",
  "packet_size": "$PACKET_SIZE",
  "created_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
MANIFEST

cat > "$PACKET/ingest_report.md" <<REPORT
# LAIA Photo SD Ingest Report

Job ID: $JOB_ID  
Source: $SRC  
Packet: $PACKET  
Completed: $(date)

## Summary

- Photo count: $PHOTO_COUNT
- Packet size: $PACKET_SIZE
- Originals copied to NAS packet
- SHA256 checksums generated
- EXIF metadata extracted when available
- JPEG previews generated when available
- Contact sheet attempted

## Packet Contents

- originals/
- previews/
- metadata/
- contact_sheet/
- logs/
- checksums.sha256
- packet_manifest.json
- ingest_report.md
REPORT

cp "$LOG" "$PACKET/logs/ingest.log"

echo "Completed: $(date)" | tee -a "$LOG"
echo "Photo count: $PHOTO_COUNT" | tee -a "$LOG"
echo "Packet size: $PACKET_SIZE" | tee -a "$LOG"
echo "Archived packet: $PACKET" | tee -a "$LOG"

#!/usr/bin/env bash
set -euo pipefail

SRC="${1:-}"

if [[ -z "$SRC" ]]; then
  echo "Usage: laia_video_ingest_mkv.sh /path/to/file.mkv"
  exit 1
fi

if [[ ! -f "$SRC" ]]; then
  echo "Source file not found: $SRC"
  exit 1
fi

ROOT="$HOME/LAIA/video_ingest"
BASENAME="$(basename "$SRC")"
NAME="${BASENAME%.*}"
STAMP="$(date +"%Y%m%d-%H%M%S")"
SAFE_NAME="$(echo "$NAME" | tr ' /:' '___' | tr -cd '[:alnum:]_.-')"
JOB_ID="${STAMP}_${SAFE_NAME}"

WORK="$ROOT/working/$JOB_ID"
ARCHIVE="$ROOT/archive/$JOB_ID"
LOG="$ROOT/logs/$JOB_ID.log"

mkdir -p "$WORK"/{original,proxy,stills,metadata,logs}

echo "LAIA Video Ingest Job: $JOB_ID" | tee "$LOG"
echo "Source: $SRC" | tee -a "$LOG"
echo "Started: $(date)" | tee -a "$LOG"

echo "Copying original..." | tee -a "$LOG"
cp "$SRC" "$WORK/original/$BASENAME"

ORIGINAL="$WORK/original/$BASENAME"

echo "Writing checksum..." | tee -a "$LOG"
shasum -a 256 "$ORIGINAL" > "$WORK/checksums.sha256"

echo "Running ffprobe..." | tee -a "$LOG"
ffprobe -v quiet -print_format json -show_format -show_streams "$ORIGINAL" > "$WORK/metadata/ffprobe.json"

if command -v mediainfo >/dev/null 2>&1; then
  echo "Running mediainfo..." | tee -a "$LOG"
  mediainfo "$ORIGINAL" > "$WORK/metadata/mediainfo.txt"
fi

echo "Creating proxy..." | tee -a "$LOG"
ffmpeg -y -i "$ORIGINAL" \
  -vf "scale='min(1280,iw)':-2" \
  -c:v libx264 -preset veryfast -crf 24 \
  -c:a aac -b:a 128k \
  "$WORK/proxy/${SAFE_NAME}_proxy.mp4" >> "$LOG" 2>&1

echo "Extracting still frames..." | tee -a "$LOG"
ffmpeg -y -i "$ORIGINAL" \
  -vf "fps=1/300,scale=640:-1" \
  "$WORK/stills/frame_%04d.jpg" >> "$LOG" 2>&1

echo "Creating contact sheet..." | tee -a "$LOG"
ffmpeg -y -pattern_type glob -i "$WORK/stills/frame_*.jpg" \
  -vf "scale=320:-1,tile=5x4" \
  "$WORK/stills/contact_sheet.jpg" >> "$LOG" 2>&1 || true

cat > "$WORK/ingest_report.md" <<EOF
# LAIA Video Ingest Report

Job ID: $JOB_ID  
Source file: $BASENAME  
Started: $STAMP  
Completed: $(date)

## Packet Contents

- Original MKV preserved
- SHA256 checksum generated
- ffprobe metadata generated
- Proxy MP4 generated
- Stills extracted every 5 minutes
- Contact sheet attempted

## Source Path

\`\`\`
$SRC
\`\`\`

## Archive Path

\`\`\`
$ARCHIVE
\`\`\`
EOF

echo "Moving packet to archive..." | tee -a "$LOG"
mv "$WORK" "$ARCHIVE"

echo "Completed: $(date)" | tee -a "$LOG"
echo "Archived packet: $ARCHIVE" | tee -a "$LOG"

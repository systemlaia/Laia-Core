#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$HOME/LAIA/archive/media}"
STAMP="$(date +%Y%m%d)"
LOG_DIR="$HOME/LAIA/ingest/logs"
REVIEW_DIR="$HOME/LAIA/ingest/review"

mkdir -p "$LOG_DIR" "$REVIEW_DIR"

echo "== LAIA INGEST CENSUS =="
echo "Root: $ROOT"
echo "Date: $STAMP"
echo

find -L "$ROOT" -type f > "$LOG_DIR/media_manifest_$STAMP.txt"

awk -F. 'NF>1 {print tolower($NF)}' "$LOG_DIR/media_manifest_$STAMP.txt" \
  | sort | uniq -c | sort -nr \
  > "$LOG_DIR/filetype_census_$STAMP.txt"

du -shL "$ROOT"/* 2>/dev/null | sort -h \
  > "$LOG_DIR/media_folder_sizes_$STAMP.txt"

find -L "$ROOT" -type f -empty \
  > "$REVIEW_DIR/empty_files_$STAMP.txt"

find -L "$ROOT" \
  -type f ! -empty \
  \( -iname "*.raf" -o -iname "*.jpg" \) \
  -exec exiftool -Model {} \; \
  | sort | uniq -c | sort -nr \
  > "$LOG_DIR/camera_census_$STAMP.txt"

find -L "$ROOT" \
  -type f ! -empty \
  -iname "*.raf" \
  -exec exiftool -FilmMode {} \; \
  | sort | uniq -c | sort -nr \
  > "$LOG_DIR/film_mode_census_$STAMP.txt"

echo "Done."
echo
echo "Manifest:"
wc -l "$LOG_DIR/media_manifest_$STAMP.txt"

echo
echo "Top file types:"
head -20 "$LOG_DIR/filetype_census_$STAMP.txt"

echo
echo "Folder sizes:"
cat "$LOG_DIR/media_folder_sizes_$STAMP.txt"

echo
echo "Camera census:"
cat "$LOG_DIR/camera_census_$STAMP.txt"

echo
echo "Film mode census:"
cat "$LOG_DIR/film_mode_census_$STAMP.txt"

echo
echo "Empty files:"
cat "$REVIEW_DIR/empty_files_$STAMP.txt"

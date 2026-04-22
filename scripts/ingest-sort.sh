#!/usr/bin/env bash

BASE=~/LAIA-Core/archive

INBOX="$BASE/scans/inbox"
DOCS="$BASE/library/documents/inbox"
DATE=$(date +%Y-%m-%d)

mkdir -p "$DOCS"

count=1

find "$INBOX" -type f -name "*.pdf" | sort | while read file; do
  new_name="${DATE}_doc_$(printf "%03d" $count).pdf"
  mv "$file" "$DOCS/$new_name"
  ((count++))
done

#!/usr/bin/env bash
set -euo pipefail

MODEL="${LAIA_LOCAL_REVIEWER_MODEL:-qwen2.5:7b}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="$REPO_ROOT/local_models/profiles/laia-qwen-reviewer.md"

if [[ $# -eq 0 ]]; then
  echo "Usage: Scripts/laia_review_local.sh \"review text\"" >&2
  exit 2
fi

if [[ ! -f "$PROFILE" ]]; then
  echo "Missing reviewer profile: $PROFILE" >&2
  exit 1
fi

REVIEW_TEXT="$*"

PROMPT="$(cat "$PROFILE")

Review text:
$REVIEW_TEXT"

ollama run "$MODEL" "$PROMPT"

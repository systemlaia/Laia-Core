#!/usr/bin/env bash
set -euo pipefail

MODEL="${LAIA_LOCAL_REVIEWER_MODEL:-qwen2.5:7b}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROFILE="$REPO_ROOT/local_models/profiles/laia-qwen-reviewer.md"

usage() {
  cat <<USAGE
Usage: $(basename "$0") "review text"

Reviews proposed LAIA changes with Ollama using local model: $MODEL
Override model with LAIA_LOCAL_REVIEWER_MODEL.
USAGE
}

if [[ "$#" -eq 0 ]]; then
  usage
  exit 2
fi

if [[ ! -f "$PROFILE" ]]; then
  echo "Missing reviewer profile: $PROFILE" >&2
  exit 1
fi

REVIEW_TEXT="$*"
PROMPT="$(cat "$PROFILE")

## Review text

$REVIEW_TEXT"

ollama run "$MODEL" "$PROMPT"

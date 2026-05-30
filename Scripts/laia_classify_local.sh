#!/usr/bin/env bash
set -euo pipefail

MODEL="${LAIA_LOCAL_CLASSIFIER_MODEL:-qwen2.5:7b}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROFILE="$REPO_ROOT/local_models/profiles/laia-qwen-classifier.md"

usage() {
  cat <<USAGE
Usage: $(basename "$0") "task text to classify"

Classifies LAIA task text with Ollama using local model: $MODEL
Override model with LAIA_LOCAL_CLASSIFIER_MODEL.
USAGE
}

if [[ "$#" -eq 0 ]]; then
  usage
  exit 2
fi

if [[ ! -f "$PROFILE" ]]; then
  echo "Missing classifier profile: $PROFILE" >&2
  exit 1
fi

TASK_TEXT="$*"
PROMPT="$(cat "$PROFILE")

## Task text

$TASK_TEXT"

ollama run "$MODEL" "$PROMPT"

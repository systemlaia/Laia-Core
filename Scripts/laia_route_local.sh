#!/usr/bin/env bash
set -euo pipefail

MODEL="${LAIA_LOCAL_ROUTER_MODEL:-qwen2.5:7b}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="$REPO_ROOT/local_models/profiles/laia-qwen-router.md"

if [[ $# -eq 0 ]]; then
  echo "Usage: Scripts/laia_route_local.sh \"task text\"" >&2
  exit 2
fi

if [[ ! -f "$PROFILE" ]]; then
  echo "Missing router profile: $PROFILE" >&2
  exit 1
fi

TASK_TEXT="$*"

PROMPT="$(cat "$PROFILE")

Task:
$TASK_TEXT"

ollama run "$MODEL" "$PROMPT"

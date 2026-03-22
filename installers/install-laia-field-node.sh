#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$REPO_ROOT/installers/common.sh"

LAIA_ROOT="${LAIA_ROOT:-$HOME/LAIA}"
SHELL_RC="$(laia_detect_shell_rc)"
RESET=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset)
      RESET=1
      shift
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: bash installers/install-laia-field-node.sh [--reset]"
      exit 1
      ;;
  esac
done

laia_log "LAIA field-node installer"

laia_log "Preflight checks"
for cmd in python3 rsync ssh; do
  if ! laia_command_exists "$cmd"; then
    echo "ERROR: required command not found: $cmd"
    exit 1
  fi
done

if [[ "$RESET" -eq 1 ]]; then
  laia_warn "Reset mode enabled: removing existing runtime at $LAIA_ROOT"
  rm -rf "$LAIA_ROOT"
fi

laia_log "Creating LAIA runtime folders"
mkdir -p "$LAIA_ROOT/core/cli"
mkdir -p "$LAIA_ROOT/core/configs"
mkdir -p "$LAIA_ROOT/core/logs"
mkdir -p "$LAIA_ROOT/core/sync"
mkdir -p "$LAIA_ROOT/core/core_client"
mkdir -p "$LAIA_ROOT/bin"

mkdir -p "$LAIA_ROOT/vault"
mkdir -p "$LAIA_ROOT/operations/ingest/photos"
mkdir -p "$LAIA_ROOT/operations/ingest/documents"
mkdir -p "$LAIA_ROOT/operations/ingest/meals"
mkdir -p "$LAIA_ROOT/operations/ingest/unsorted"
mkdir -p "$LAIA_ROOT/operations/reviews"
mkdir -p "$LAIA_ROOT/operations/exports"
mkdir -p "$LAIA_ROOT/operations/requests"
mkdir -p "$LAIA_ROOT/operations/results"

mkdir -p "$LAIA_ROOT/templates"
mkdir -p "$LAIA_ROOT/archive"

laia_log "Creating Python virtual environment if needed"
if [[ ! -x "$LAIA_ROOT/.venv/bin/python" ]]; then
  python3 -m venv "$LAIA_ROOT/.venv"
fi

laia_log "Installing Python dependencies"
"$LAIA_ROOT/.venv/bin/pip" install --upgrade pip
if [[ -f "$REPO_ROOT/requirements.txt" ]]; then
  "$LAIA_ROOT/.venv/bin/pip" install -r "$REPO_ROOT/requirements.txt"
else
  "$LAIA_ROOT/.venv/bin/pip" install PyYAML
fi

laia_log "Refreshing code packages"
rsync -a --delete "$REPO_ROOT/cli/" "$LAIA_ROOT/core/cli/"
rsync -a --delete "$REPO_ROOT/sync/" "$LAIA_ROOT/core/sync/"
rsync -a --delete "$REPO_ROOT/core_client/" "$LAIA_ROOT/core/core_client/"

laia_log "Installing launcher"
laia_write_wrapper "$LAIA_ROOT/bin/laia"

laia_log "Installing config defaults"
mkdir -p "$LAIA_ROOT/core/configs/defaults"
if [[ -f "$REPO_ROOT/configs/node/field-node.yaml" ]]; then
  cp "$REPO_ROOT/configs/node/field-node.yaml" "$LAIA_ROOT/core/configs/defaults/field-node.yaml"
fi
if [[ -f "$REPO_ROOT/configs/node/core-node.yaml" ]]; then
  cp "$REPO_ROOT/configs/node/core-node.yaml" "$LAIA_ROOT/core/configs/defaults/core-node.yaml"
fi
if [[ -f "$REPO_ROOT/configs/sync/sync-config.yaml" ]]; then
  cp "$REPO_ROOT/configs/sync/sync-config.yaml" "$LAIA_ROOT/core/configs/defaults/sync-config.yaml"
fi
if [[ -f "$REPO_ROOT/configs/core/core-services.yaml" ]]; then
  cp "$REPO_ROOT/configs/core/core-services.yaml" "$LAIA_ROOT/core/configs/defaults/core-services.yaml"
fi
if [[ -f "$REPO_ROOT/configs/models/model-routing.yaml" ]]; then
  cp "$REPO_ROOT/configs/models/model-routing.yaml" "$LAIA_ROOT/core/configs/defaults/model-routing.yaml"
fi

laia_log "Installing active configs only if missing"
if [[ -f "$REPO_ROOT/configs/node/field-node.yaml" ]]; then
  laia_copy_if_missing "$REPO_ROOT/configs/node/field-node.yaml" "$LAIA_ROOT/core/configs/node.yaml"
fi
if [[ -f "$REPO_ROOT/configs/sync/sync-config.yaml" ]]; then
  laia_copy_if_missing "$REPO_ROOT/configs/sync/sync-config.yaml" "$LAIA_ROOT/core/configs/sync-config.yaml"
fi
if [[ -f "$REPO_ROOT/configs/core/core-services.yaml" ]]; then
  laia_copy_if_missing "$REPO_ROOT/configs/core/core-services.yaml" "$LAIA_ROOT/core/configs/core-services.yaml"
fi
if [[ -f "$REPO_ROOT/configs/models/model-routing.yaml" ]]; then
  laia_copy_if_missing "$REPO_ROOT/configs/models/model-routing.yaml" "$LAIA_ROOT/core/configs/model-routing.yaml"
fi

laia_log "Installing templates (non-destructive)"
if [[ -d "$REPO_ROOT/templates/obsidian" ]]; then
  while IFS= read -r -d '' src; do
    rel="${src#$REPO_ROOT/templates/obsidian/}"
    laia_copy_if_missing "$src" "$LAIA_ROOT/templates/$rel"
  done < <(find "$REPO_ROOT/templates/obsidian" -type f -print0)
elif [[ -d "$REPO_ROOT/templates" ]]; then
  while IFS= read -r -d '' src; do
    rel="${src#$REPO_ROOT/templates/}"
    laia_copy_if_missing "$src" "$LAIA_ROOT/templates/$rel"
  done < <(find "$REPO_ROOT/templates" -type f -print0)
fi

laia_log "Installing starter vault scaffold (only missing files)"
if [[ -d "$REPO_ROOT/vault" ]]; then
  while IFS= read -r -d '' src; do
    rel="${src#$REPO_ROOT/vault/}"
    laia_copy_if_missing "$src" "$LAIA_ROOT/vault/$rel"
  done < <(find "$REPO_ROOT/vault" -type f -print0)
fi

laia_log "Configuring shell"
laia_append_if_missing 'export LAIA_ROOT="$HOME/LAIA"' "$SHELL_RC"
laia_append_if_missing 'export PATH="$HOME/LAIA/bin:$PATH"' "$SHELL_RC"
laia_append_if_missing 'alias laia="$HOME/LAIA/bin/laia"' "$SHELL_RC"

laia_log "Running sanity check"
PYTHONPATH="$LAIA_ROOT/core" "$LAIA_ROOT/.venv/bin/python" "$LAIA_ROOT/core/cli/laia.py" doctor || {
  echo "ERROR: sanity check failed"
  exit 1
}

echo ""
echo "===================================="
echo "     LAIA FIELD NODE INSTALLED"
echo "===================================="
echo ""
echo "Mode: $([[ "$RESET" -eq 1 ]] && echo reset || echo update/preserve)"
echo ""
echo "Preserved by default:"
echo "  - vault/"
echo "  - operations/"
echo "  - archive/"
echo ""
echo "Updated on each run:"
echo "  - core/cli"
echo "  - core/sync"
echo "  - core/core_client"
echo "  - launcher"
echo "  - venv dependencies"
echo "  - config defaults"
echo ""
echo "Reload shell:"
echo "  source \"$SHELL_RC\""
echo ""
echo "Then test:"
echo "  laia doctor"
echo "  laia day"
echo "  laia focus"
echo "  laia sync status"
echo ""
echo "Reset everything only when needed:"
echo "  bash installers/install-laia-field-node.sh --reset"
echo ""

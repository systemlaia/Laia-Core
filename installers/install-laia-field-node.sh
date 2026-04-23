#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$REPO_ROOT/installers/common.sh"

LAIA_ROOT="${LAIA_ROOT:-$HOME/LAIA}"
SHELL_RC="$(laia_detect_shell_rc)"
RESET=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset)
      RESET=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: bash installers/install-laia-field-node.sh [--reset] [--dry-run]"
      exit 1
      ;;
  esac
done

LOG_DIR="$LAIA_ROOT/core/logs"
LOG_FILE="$LOG_DIR/install.log"

mkdir -p "$LOG_DIR"

if [[ "$DRY_RUN" -eq 0 ]]; then
  exec > >(tee -a "$LOG_FILE") 2>&1
fi

run_cmd() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] '
    printf '%q ' "$@"
    printf '\n'
  else
    "$@"
  fi
}

laia_log "LAIA field-node installer"

laia_log "Installer context"
echo "REPO_ROOT: $REPO_ROOT"
echo "LAIA_ROOT: $LAIA_ROOT"
echo "SHELL_RC:  $SHELL_RC"
echo "MODE:      $([[ "$RESET" -eq 1 ]] && echo reset || echo update/preserve)"
echo "DRY_RUN:   $DRY_RUN"

laia_log "Preflight checks"
for cmd in python3 rsync ssh; do
  if ! laia_command_exists "$cmd"; then
    echo "ERROR: required command not found: $cmd"
    exit 1
  fi
done

if [[ "$RESET" -eq 1 ]]; then
  laia_warn "Reset mode enabled: removing existing runtime at $LAIA_ROOT"
  run_cmd rm -rf "$LAIA_ROOT"
fi

laia_log "Creating LAIA runtime folders"
run_cmd mkdir -p "$LAIA_ROOT/core/cli"
run_cmd mkdir -p "$LAIA_ROOT/core/configs"
run_cmd mkdir -p "$LAIA_ROOT/core/logs"
run_cmd mkdir -p "$LAIA_ROOT/core/sync"
run_cmd mkdir -p "$LAIA_ROOT/core/core_client"
run_cmd mkdir -p "$LAIA_ROOT/bin"

run_cmd mkdir -p "$LAIA_ROOT/vault"
run_cmd mkdir -p "$LAIA_ROOT/operations/ingest/photos"
run_cmd mkdir -p "$LAIA_ROOT/operations/ingest/documents"
run_cmd mkdir -p "$LAIA_ROOT/operations/ingest/meals"
run_cmd mkdir -p "$LAIA_ROOT/operations/ingest/unsorted"
run_cmd mkdir -p "$LAIA_ROOT/operations/reviews"
run_cmd mkdir -p "$LAIA_ROOT/operations/exports"
run_cmd mkdir -p "$LAIA_ROOT/operations/requests"
run_cmd mkdir -p "$LAIA_ROOT/operations/results"

run_cmd mkdir -p "$LAIA_ROOT/templates"
run_cmd mkdir -p "$LAIA_ROOT/archive"

laia_log "Creating Python virtual environment if needed"
if [[ ! -x "$LAIA_ROOT/.venv/bin/python" ]]; then
  run_cmd python3 -m venv "$LAIA_ROOT/.venv"
else
  echo "Existing virtual environment found at $LAIA_ROOT/.venv"
fi

laia_log "Installing Python dependencies"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] $LAIA_ROOT/.venv/bin/pip install --upgrade pip"
  if [[ -f "$REPO_ROOT/requirements.txt" ]]; then
    echo "[dry-run] $LAIA_ROOT/.venv/bin/pip install -r $REPO_ROOT/requirements.txt"
  else
    echo "[dry-run] $LAIA_ROOT/.venv/bin/pip install PyYAML"
  fi
else
  "$LAIA_ROOT/.venv/bin/pip" install --upgrade pip
  if [[ -f "$REPO_ROOT/requirements.txt" ]]; then
    "$LAIA_ROOT/.venv/bin/pip" install -r "$REPO_ROOT/requirements.txt"
  else
    "$LAIA_ROOT/.venv/bin/pip" install PyYAML
  fi
fi

laia_log "Refreshing code packages"
run_cmd rsync -a --delete "$REPO_ROOT/cli/" "$LAIA_ROOT/core/cli/"
run_cmd rsync -a --delete "$REPO_ROOT/sync/" "$LAIA_ROOT/core/sync/"
run_cmd rsync -a --delete "$REPO_ROOT/core_client/" "$LAIA_ROOT/core/core_client/"

laia_log "Installing launcher"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] write launcher to $LAIA_ROOT/bin/laia"
else
  laia_write_wrapper "$LAIA_ROOT/bin/laia"
fi

laia_log "Installing config defaults"
run_cmd mkdir -p "$LAIA_ROOT/core/configs/defaults"
if [[ -f "$REPO_ROOT/configs/node/field-node.yaml" ]]; then
  run_cmd cp "$REPO_ROOT/configs/node/field-node.yaml" "$LAIA_ROOT/core/configs/defaults/field-node.yaml"
fi
if [[ -f "$REPO_ROOT/configs/node/core-node.yaml" ]]; then
  run_cmd cp "$REPO_ROOT/configs/node/core-node.yaml" "$LAIA_ROOT/core/configs/defaults/core-node.yaml"
fi
if [[ -f "$REPO_ROOT/configs/sync/sync-config.yaml" ]]; then
  run_cmd cp "$REPO_ROOT/configs/sync/sync-config.yaml" "$LAIA_ROOT/core/configs/defaults/sync-config.yaml"
fi
if [[ -f "$REPO_ROOT/configs/core/core-services.yaml" ]]; then
  run_cmd cp "$REPO_ROOT/configs/core/core-services.yaml" "$LAIA_ROOT/core/configs/defaults/core-services.yaml"
fi
if [[ -f "$REPO_ROOT/configs/models/model-routing.yaml" ]]; then
  run_cmd cp "$REPO_ROOT/configs/models/model-routing.yaml" "$LAIA_ROOT/core/configs/defaults/model-routing.yaml"
fi

laia_log "Installing active configs only if missing"
if [[ "$DRY_RUN" -eq 1 ]]; then
  if [[ -f "$REPO_ROOT/configs/node/field-node.yaml" ]]; then
    echo "[dry-run] copy-if-missing $REPO_ROOT/configs/node/field-node.yaml -> $LAIA_ROOT/core/configs/node.yaml"
  fi
  if [[ -f "$REPO_ROOT/configs/sync/sync-config.yaml" ]]; then
    echo "[dry-run] copy-if-missing $REPO_ROOT/configs/sync/sync-config.yaml -> $LAIA_ROOT/core/configs/sync-config.yaml"
  fi
  if [[ -f "$REPO_ROOT/configs/core/core-services.yaml" ]]; then
    echo "[dry-run] copy-if-missing $REPO_ROOT/configs/core/core-services.yaml -> $LAIA_ROOT/core/configs/core-services.yaml"
  fi
  if [[ -f "$REPO_ROOT/configs/models/model-routing.yaml" ]]; then
    echo "[dry-run] copy-if-missing $REPO_ROOT/configs/models/model-routing.yaml -> $LAIA_ROOT/core/configs/model-routing.yaml"
  fi
else
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
fi

laia_log "Installing templates (non-destructive)"
if [[ -d "$REPO_ROOT/templates/obsidian" ]]; then
  while IFS= read -r -d '' src; do
    rel="${src#$REPO_ROOT/templates/obsidian/}"
    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "[dry-run] copy-if-missing $src -> $LAIA_ROOT/templates/$rel"
    else
      laia_copy_if_missing "$src" "$LAIA_ROOT/templates/$rel"
    fi
  done < <(find "$REPO_ROOT/templates/obsidian" -type f -print0)
elif [[ -d "$REPO_ROOT/templates" ]]; then
  while IFS= read -r -d '' src; do
    rel="${src#$REPO_ROOT/templates/}"
    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "[dry-run] copy-if-missing $src -> $LAIA_ROOT/templates/$rel"
    else
      laia_copy_if_missing "$src" "$LAIA_ROOT/templates/$rel"
    fi
  done < <(find "$REPO_ROOT/templates" -type f -print0)
fi

laia_log "Installing starter vault scaffold (only missing files)"
if [[ -d "$REPO_ROOT/vault" ]]; then
  while IFS= read -r -d '' src; do
    rel="${src#$REPO_ROOT/vault/}"
    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "[dry-run] copy-if-missing $src -> $LAIA_ROOT/vault/$rel"
    else
      laia_copy_if_missing "$src" "$LAIA_ROOT/vault/$rel"
    fi
  done < <(find "$REPO_ROOT/vault" -type f -print0)
fi

laia_log "Configuring shell"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo '[dry-run] append-if-missing export LAIA_ROOT="$HOME/LAIA"'
  echo '[dry-run] append-if-missing export PATH="$HOME/LAIA/bin:$PATH"'
  echo '[dry-run] append-if-missing alias laia="$HOME/LAIA/bin/laia"'
else
  laia_append_if_missing 'export LAIA_ROOT="$HOME/LAIA"' "$SHELL_RC"
  laia_append_if_missing 'export PATH="$HOME/LAIA/bin:$PATH"' "$SHELL_RC"
  laia_append_if_missing 'alias laia="$HOME/LAIA/bin/laia"' "$SHELL_RC"
fi

laia_log "Running sanity check"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] PYTHONPATH=\"$LAIA_ROOT/core\" \"$LAIA_ROOT/.venv/bin/python\" \"$LAIA_ROOT/core/cli/laia.py\" doctor"
else
  PYTHONPATH="$LAIA_ROOT/core" "$LAIA_ROOT/.venv/bin/python" "$LAIA_ROOT/core/cli/laia.py" doctor || {
    echo "ERROR: sanity check failed"
    exit 1
  }
fi

echo ""
echo "===================================="
echo "     LAIA FIELD NODE INSTALLED"
echo "===================================="
echo ""
echo "Mode: $([[ "$RESET" -eq 1 ]] && echo reset || echo update/preserve)"
echo "Dry run: $([[ "$DRY_RUN" -eq 1 ]] && echo yes || echo no)"
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
echo "Preview without changes:"
echo "  bash installers/install-laia-field-node.sh --dry-run"
echo ""
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$REPO_ROOT/installers/common.sh"

LAIA_ROOT="${LAIA_ROOT:-$HOME/LAIA}"
SHELL_RC="$(laia_detect_shell_rc)"

laia_log "LAIA field-node installer"

laia_log "Preflight checks"
for cmd in python3 pip3 rsync ssh; do
  if ! laia_command_exists "$cmd"; then
    echo "ERROR: required command not found: $cmd"
    exit 1
  fi
done

laia_log "Creating LAIA runtime folders"
mkdir -p "$LAIA_ROOT/core/cli"
mkdir -p "$LAIA_ROOT/core/configs"
mkdir -p "$LAIA_ROOT/core/logs"
mkdir -p "$LAIA_ROOT/vault"
mkdir -p "$LAIA_ROOT/operations/ingest/photos"
mkdir -p "$LAIA_ROOT/operations/ingest/documents"
mkdir -p "$LAIA_ROOT/operations/ingest/meals"
mkdir -p "$LAIA_ROOT/operations/ingest/unsorted"
mkdir -p "$LAIA_ROOT/operations/reviews"
mkdir -p "$LAIA_ROOT/operations/exports"
mkdir -p "$LAIA_ROOT/templates"
mkdir -p "$LAIA_ROOT/archive"

laia_log "Creating Python virtual environment"
python3 -m venv "$LAIA_ROOT/.venv"

laia_log "Installing Python dependencies"
"$LAIA_ROOT/.venv/bin/pip" install --upgrade pip
if [ -f "$REPO_ROOT/requirements.txt" ]; then
  "$LAIA_ROOT/.venv/bin/pip" install -r "$REPO_ROOT/requirements.txt"
else
  "$LAIA_ROOT/.venv/bin/pip" install PyYAML
fi

laia_log "Copying CLI"
rsync -a "$REPO_ROOT/cli/" "$LAIA_ROOT/core/cli/"

laia_log "Copying starter vault scaffold"
rsync -a "$REPO_ROOT/vault/" "$LAIA_ROOT/vault/"

laia_log "Copying templates"
if [ -d "$REPO_ROOT/templates/obsidian" ]; then
  rsync -a "$REPO_ROOT/templates/obsidian/" "$LAIA_ROOT/templates/"
else
  rsync -a "$REPO_ROOT/templates/" "$LAIA_ROOT/templates/"
fi

laia_log "Copying field-node config"
cp "$REPO_ROOT/configs/node/field-node.yaml" "$LAIA_ROOT/core/configs/node.yaml"

laia_log "Copying sync config"
cp "$REPO_ROOT/configs/sync/sync-config.yaml" "$LAIA_ROOT/core/configs/sync-config.yaml"

laia_log "Configuring shell"
laia_append_if_missing 'export LAIA_ROOT="$HOME/LAIA"' "$SHELL_RC"
laia_append_if_missing 'alias laia="$HOME/LAIA/.venv/bin/python $HOME/LAIA/core/cli/laia.py"' "$SHELL_RC"

laia_log "Running sanity check"
export LAIA_ROOT
"$LAIA_ROOT/.venv/bin/python" "$LAIA_ROOT/core/cli/laia.py" doctor || {
  echo "ERROR: sanity check failed"
  exit 1
}

echo ""
echo "===================================="
echo "     LAIA FIELD NODE INSTALLED"
echo "===================================="
echo ""

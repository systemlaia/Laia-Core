#!/usr/bin/env bash
set -euo pipefail

laia_log() {
  echo ""
  echo "==> $1"
}

laia_append_if_missing() {
  local line="$1"
  local file="$2"
  touch "$file"
  grep -Fqx "$line" "$file" || echo "$line" >> "$file"
}

laia_command_exists() {
  command -v "$1" >/dev/null 2>&1
}

laia_detect_shell_rc() {
  if [ -n "${BASH_VERSION:-}" ]; then
    echo "$HOME/.bashrc"
  else
    echo "$HOME/.zshrc"
  fi
}

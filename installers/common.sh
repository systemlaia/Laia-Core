#!/usr/bin/env bash
set -euo pipefail

laia_log() {
  echo ""
  echo "==> $1"
}

laia_warn() {
  echo ""
  echo "WARN: $1"
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

laia_copy_if_missing() {
  local src="$1"
  local dst="$2"
  if [ ! -e "$dst" ]; then
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
  fi
}

laia_write_wrapper() {
  local target="$1"
  cat > "$target" <<'WRAP'
#!/usr/bin/env bash
set -euo pipefail
export LAIA_ROOT="$HOME/LAIA"
export PYTHONPATH="$LAIA_ROOT/core"
exec "$LAIA_ROOT/.venv/bin/python" "$LAIA_ROOT/core/cli/laia.py" "$@"
WRAP
  chmod +x "$target"
}

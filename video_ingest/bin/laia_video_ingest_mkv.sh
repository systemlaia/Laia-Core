#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "Deprecated: use 'laia video ingest FILE'." >&2
exec "$REPO_ROOT/bin/laia" video ingest "$@"

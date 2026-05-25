#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "== LAIA Agent Smoke Test =="

if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "== Python compile =="
python -m py_compile cli/laia.py

echo "== Paths doctor =="
python cli/laia.py paths doctor

echo "== Personal OS doctor =="
python cli/laia.py personal-os doctor

echo "== Packet list =="
python cli/laia.py packet list

echo "PASS: LAIA agent smoke test complete"

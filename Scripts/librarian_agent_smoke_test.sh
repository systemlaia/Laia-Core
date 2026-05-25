#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "== LAIA Librarian Agent Smoke Test =="

if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "== Python compile =="
python -m py_compile cli/laia.py

echo "== Librarian status =="
python cli/laia.py librarian status

echo "== Librarian review =="
python cli/laia.py librarian review --write

echo "== Librarian approvals =="
python cli/laia.py librarian approvals --write

echo "== Librarian actions =="
python cli/laia.py librarian actions --write

echo "PASS: LAIA librarian agent smoke test complete"

echo
echo "NOTE: This test may update generated Blue Book notes."
echo "NOTE: It does NOT run librarian retrieve --execute."

You are working in the LAIA Core repository at ~/LAIA/core.

Read AGENTS.md first.

Task file:
agent_tasks/sample-fix-receipt-wording.md

Goal:
Fix the Librarian retrieval receipt wording in cli/laia.py.

Required change:
Replace:
“It did not move, rename, delete, copy, or modify archive originals.”

with:
“It did not move, rename, delete, or modify archive originals. It copied approved files into a retrieval folder.”

Allowed file:
cli/laia.py

Forbidden:
- Do not write inside /Volumes/Public.
- Do not modify archive originals.
- Do not run librarian retrieve --execute.
- Do not commit.

After editing, run:
scripts/agent_smoke_test.sh
scripts/agent_guard_check.py

Then show:
git status -sb
git --no-pager diff -- cli/laia.py

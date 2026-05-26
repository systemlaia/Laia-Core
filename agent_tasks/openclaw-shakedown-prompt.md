You are working in the LAIA Core repository at /workspace/laia-core.

Read AGENTS.md first.

Complete:
agent_tasks/sample-fix-receipt-wording.md

Edit only allowed files.
Do not write inside /Volumes/Public.
Do not modify archive originals.
Do not run librarian retrieve --execute.
Do not commit.

After editing, run:
scripts/agent_smoke_test.sh
scripts/agent_guard_check.py

Then show:
git status -sb
git --no-pager diff -- cli/laia.py

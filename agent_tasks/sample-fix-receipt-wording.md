# Fix Librarian Retrieval Receipt Wording

## Title

Fix Librarian retrieval receipt wording.

## Goal

Replace the misleading phrase:

> It did not move, rename, delete, copy, or modify archive originals.

With:

> It did not move, rename, delete, or modify archive originals. It copied approved files into a retrieval folder.

## Allowed Files

- `cli/laia.py`

## Forbidden Files

- `/Volumes/Public`
- mounted NAS archive shares
- `~/LAIA_ARCHIVE`
- archive originals
- `~/LAIA/archive/duplicate-vaults`

## Commands To Run

```sh
scripts/agent_smoke_test.sh
scripts/agent_guard_check.py
git status -sb
git --no-pager diff -- cli/laia.py
```

## Safety Notes

- Preserve archive originals.
- Do not write inside `/Volumes/Public`.
- Do not run `librarian retrieve --execute`.

## Expected Output

- The receipt wording in `cli/laia.py` is updated.
- Smoke test passes or failures are reported clearly.
- Guard check output is shown.
- Git status and diff are shown.

## Commit Policy

Do not auto-commit.

## Human Approval Required

- Any file outside `cli/laia.py`.
- Any retrieval execution.
- Any commit.

# Agent Task Template

## Title

-

## Goal

-

## Allowed Files

-

## Forbidden Files

- `/Volumes/Public`
- mounted NAS archive shares
- `~/LAIA_ARCHIVE`
- archive originals

## Commands To Run

```sh
scripts/agent_smoke_test.sh
scripts/agent_guard_check.py
git status -sb
git --no-pager diff
```

## Safety Notes

- Preserve archive originals.
- Do not write inside `/Volumes/Public`.
- Do not run destructive shell commands.
- Do not run `librarian retrieve --execute` unless a human explicitly asks.

## Expected Output

-

## Commit Policy

- Do not auto-commit.
- Stop after showing status and diff unless the human explicitly asks for a commit.

## Human Approval Required

- Before any archive-affecting operation.
- Before any `librarian retrieve --execute`.
- Before any commit.

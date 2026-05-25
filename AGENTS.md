# LAIA Local Agent Rules

This repository can be worked on by local coding agents such as OpenClaw, Aider, Claude Code, Codex, Cursor, and Continue. These rules are the shared contract for safe work.

## Canonical Paths

- Core repo: `~/LAIA/core`
- LAIA root: `~/LAIA`
- Active Blue Book vault: `~/Documents/Blue Book`
- Core state: `~/LAIA/state`
- Packets: `~/LAIA/packets`
- Retrievals: `~/LAIA/retrievals`
- NAS/archive mount: `/Volumes/Public`
- Duplicate vault archive: `~/LAIA/archive/duplicate-vaults`

Use `LAIA_ROOT` when the CLI supports it. Use `LAIA_VAULT_PATH` only when the human explicitly wants to override the active Blue Book vault.

## Allowed Write Areas

Write only where the task explicitly requires it. The normal allowed areas are:

- `~/LAIA/core`
- `~/LAIA/state`
- `~/LAIA/packets`
- `~/LAIA/retrievals`
- `~/Documents/Blue Book/04_PACKETS`
- `~/Documents/Blue Book/05_REPORTS`
- `~/Documents/Blue Book/07_SYSTEM`

Edit the smallest possible set of files. Preserve existing behavior unless the task asks for a behavior change.

## Forbidden Write Areas

Do not write to:

- `/Volumes/Public`
- mounted NAS archive shares
- `~/LAIA_ARCHIVE`
- archive originals
- `~/LAIA/archive/duplicate-vaults`, unless the task explicitly says archive duplicate management

Do not move, rename, delete, overwrite, or modify archive originals. Do not run destructive shell commands.

## Librarian Safety Doctrine

Preserve archive originals. Librarian commands may inspect manifests, write review notes, write packet notes, write reports, and write retrieval metadata in approved LAIA or Blue Book locations.

Never run `librarian retrieve --execute` unless a human explicitly asks for that exact retrieval execution. Do not write inside `/Volumes/Public` or mounted NAS archive shares.

Retrieval workflows may copy approved files into `~/LAIA/retrievals`, but only through explicitly requested commands. Packet closure records workflow state only; it must not modify archive originals.

## Required Checks

For ordinary CLI-safe changes, run:

```sh
scripts/agent_smoke_test.sh
scripts/agent_guard_check.py
```

For Librarian workflow changes, also run:

```sh
scripts/librarian_agent_smoke_test.sh
```

If a test cannot be run, say why. Do not hide failures.

## Git And Commit Policy

Do not auto-commit. The human commits.

Before stopping, always show:

```sh
git status -sb
git --no-pager diff
```

Stop after showing the diff unless the human explicitly asks you to commit or continue.

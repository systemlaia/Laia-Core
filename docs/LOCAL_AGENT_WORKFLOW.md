# Local Agent Workflow

Use this workflow when a local coding agent works on LAIA Core.

## Workflow

1. Create or choose an agent task file in `agent_tasks/`.
2. The agent reads `AGENTS.md`.
3. The agent edits only files allowed by the task and by `AGENTS.md`.
4. The agent runs the smoke test:

   ```sh
   scripts/agent_smoke_test.sh
   ```

5. The agent runs the guard check:

   ```sh
   scripts/agent_guard_check.py
   ```

6. The agent shows:

   ```sh
   git status -sb
   git --no-pager diff
   ```

7. The human reviews the diff and test output.
8. The human commits.

For Librarian workflow changes, also run:

```sh
scripts/librarian_agent_smoke_test.sh
```

That smoke test may update generated Blue Book notes in approved `07_SYSTEM` locations. It must not run `librarian retrieve --execute` and must not write inside `/Volumes/Public`.

## Example Task

Use `agent_tasks/sample-fix-receipt-wording.md` for a small wording-only task:

- Fix Librarian retrieval receipt wording.
- Edit only `cli/laia.py`.
- Run `scripts/agent_smoke_test.sh`.
- Run `scripts/agent_guard_check.py`.
- Show `git status -sb` and the diff.
- Do not auto-commit.

## OpenClaw Notes

- Keep the gateway local.
- Use a strong token or password.
- Do not install untrusted skills.
- Do not expose the gateway to LAN or internet unless intentionally configured.
- Avoid third-party skills unless inspected.

## Safety Reminder

Preserve archive originals. Do not write inside `/Volumes/Public`, mounted NAS archive shares, or archive-original locations. Do not move, rename, delete, overwrite, or modify archive originals. Do not auto-commit.

# OpenClaw Host Operating Lane

This note documents the current working LAIA agent setup and routing model. It is intended as an operational reference for choosing the right lane for repo work, local review work, and experimental agent work.

## Working lanes

### Host OpenClaw + OpenAI API: operator/editor lane

The host OpenClaw setup backed by the OpenAI API is the working operator and editor lane for LAIA Core. Use this lane for coordinated repo editing, documentation updates, operator tasks, and guarded changes where an agent needs to inspect files, make targeted edits, and run checks.

### VS Code/Codex: direct development lane

VS Code/Codex is the direct development lane. Use it for hands-on implementation work, interactive coding, and local developer flow inside the LAIA Core repository.

### Ollama/qwen2.5:7b: local clerk/classifier/reviewer lane

Ollama with `qwen2.5:7b` is the local clerk, classifier, and reviewer lane. Route local classification, summaries, extraction, lightweight review, and similar non-destructive analysis tasks here when paid API-backed editing is not required.

### Parked experimental lanes

The Docker OpenClaw setup and Ollama-inside-OpenClaw setup are currently parked experimental lanes. Do not treat either as the primary operating path for LAIA Core until the human explicitly reactivates or promotes one of them.

## Guardrails supplied by LAIA Core

LAIA Core provides scripts that should be used as guardrails after ordinary CLI-safe changes:

- `scripts/agent_smoke_test.sh`
- `scripts/agent_guard_check.py`

Run these checks before reporting completion unless the task says otherwise or a check cannot be run. Report any failure plainly.

## Safety rules

The following rules apply across all lanes:

- Do not modify `/Volumes/Public`.
- Do not modify archive originals.
- Do not run `librarian retrieve --execute` unless explicitly approved by the human.
- Do not auto-commit unless requested.
- Human approval remains required before dangerous or archive-affecting actions.

## Host OpenClaw path notes

For the working host OpenClaw install:

- OpenClaw config lives at `/Users/paulroberson/.openclaw/openclaw.json`.
- The safe workspace path is `/Users/paulroberson/.openclaw/workspace`.
- The Docker path `/home/node/.openclaw/workspace` is a bad path for host installs and must not be used there.

## Paid vs local routing

Use paid/API-backed and local lanes deliberately:

- OpenAI/OpenClaw handles repo editing and operator tasks.
- qwen/Ollama handles local classification, summaries, extraction, and review.
- Dangerous actions, archive-affecting actions, retrieval execution, and anything touching protected storage require human approval first.

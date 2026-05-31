# LAIA Agent Routing

This note explains how to choose between LAIA's current agent lanes.

## Lanes

### local_classifier

Use `Scripts/laia_classify_local.sh` when the task is only asking which LAIA category a task belongs to.

Example:

    Scripts/laia_classify_local.sh "catalog salvaged components from photos for CAD"

### local_reviewer

Use `Scripts/laia_review_local.sh` for low-risk review, summaries, safety-rule extraction, and readbacks.

Example:

    Scripts/laia_review_local.sh "Review this change: added a docs note. Smoke and guard checks passed."

### host_openclaw

Use host OpenClaw with the OpenAI API for guarded repo editing and operator/editor tasks, especially when a task has clear allowed files and required checks.

### vscode_codex

Use VS Code/Codex for direct development, debugging, interactive coding, and multi-step implementation work that benefits from IDE context.

### human_only

Use human-only approval/action for dangerous, archive-affecting, physical-world, credential, destructive, or ambiguous tasks.

Examples include:

- modifying `/Volumes/Public`
- modifying archive originals
- running `librarian retrieve --execute`
- credential changes
- real-world vehicle, home, electrical, or physical safety risks

## Safety rules

- Do not modify `/Volumes/Public`.
- Do not modify archive originals.
- Do not run `librarian retrieve --execute` unless explicitly approved.
- Human approval is required before dangerous or archive-affecting actions.
- Do not auto-commit unless requested.

## Routing helper

Use the local router for a quick recommendation:

    Scripts/laia_route_local.sh "Edit a docs file and run smoke checks"

The router returns:

    lane: <lane>
    reason: <one sentence>
    next_step: <short command or instruction>

## Current operating split

- OpenAI/OpenClaw is the operator/editor lane.
- qwen/Ollama is the local clerk/reviewer lane.
- VS Code/Codex is the direct development lane.
- Human approval remains the final authority for dangerous or archive-affecting actions.

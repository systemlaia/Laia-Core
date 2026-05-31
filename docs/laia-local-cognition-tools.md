# LAIA Local Cognition Tools

LAIA Core has lightweight local qwen/Ollama helpers for classification, review, and routing. These tools use `qwen2.5:7b` as the default local model.

Local tools are clerks and reviewers, not operators. They do not replace human approval. Dangerous or archive-affecting tasks remain `human_only`. Paid/OpenAI/OpenClaw remains the operator/editor lane, and VS Code/Codex remains the direct development lane.

## `Scripts/laia_classify_local.sh`

Purpose: classify a task into a LAIA category.

Best for: category routing, sorting task notes, deciding where work belongs.

Example:

```sh
Scripts/laia_classify_local.sh "catalog salvaged components from photos for CAD"
```

## `Scripts/laia_review_local.sh`

Purpose: review a proposed low-risk change.

Best for: safety readbacks, low-risk review, summarizing files touched, escalation suggestions.

Example:

```sh
Scripts/laia_review_local.sh "Review this change: updated a docs note. Smoke and guard checks passed."
```

## `Scripts/laia_route_local.sh`

Purpose: recommend the right working lane.

Best for: deciding between `local_classifier`, `local_reviewer`, `host_openclaw`, `vscode_codex`, and `human_only`.

Example:

```sh
Scripts/laia_route_local.sh "Edit cli/laia.py to change a help string and run smoke checks."
```

## Operating reminders

- `qwen2.5:7b` is the default local model.
- Local tools are clerks/reviewers, not operators.
- Local tools do not replace human approval.
- Dangerous or archive-affecting tasks remain `human_only`.
- Paid/OpenAI/OpenClaw remains the operator/editor lane.
- VS Code/Codex remains the direct development lane.

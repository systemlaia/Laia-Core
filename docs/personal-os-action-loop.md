# Personal OS Action Loop

Use these commands to move from morning state to a concrete next action without changing archive originals or running risky retrieval execution.

## Commands

```sh
python3 cli/laia.py day ops
```

Purpose: show current operating state.

```sh
python3 cli/laia.py day ops --route
```

Purpose: fast rule-based routing for active/review packets.

```sh
python3 cli/laia.py day ops --route-ai
```

Purpose: optional qwen/Ollama routing, slower and experimental.

```sh
python3 cli/laia.py day next
```

Purpose: recommend the next packet/action.

```sh
python3 cli/laia.py day next --show
```

Purpose: recommend the next packet and show its detail view.

```sh
python3 cli/laia.py packet show <packet_id>
```

Purpose: inspect a packet directly.

## Loop

1. Check state.
2. Route work.
3. Select next action.
4. Inspect packet.
5. Act with the right lane.
6. Run smoke/guard checks before committing.

## Lane Reminders

- Local tools are clerks/reviewers.
- Host OpenClaw/OpenAI is operator/editor.
- VS Code/Codex is direct development.
- Human approval is required for dangerous/archive-affecting actions.

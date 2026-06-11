---
type: context_packet
packet_id: 20260514-171802-laia-core
topic: LAIA Core
source: blue_book
source_count: 3
generated_at: 2026-05-14T17:18:46.857661
---

# Context Packet — LAIA Core

- Packet ID: `20260514-171802-laia-core`
- Vault: `/Users/iv/LAIA/vaults/Blue Book`
- Sources: `3`
- Min score: `30`

## Model Summary

# Summary

This context packet contains information about LAIA's Core, specifically its Stable Baseline and Dashboard.

## What this packet contains

1. **LAIA Core Snapshot - OpenClaw Stable Baseline**: Detailed configuration and status of the stable LAIA Core baseline as of May 8th, 2026. This includes the runtime status, architecture, ports, active agents, and workspace files. (Source: [1])

2. **LAIA Core Stable Baseline**: A more general overview of the LAIA Core stable baseline, including its core stack, rules for stability maintenance, and recovery commands. (Source: [2])

3. **🧠 LAIA CORE DASHBOARD**: A dashboard interface for interacting with various systems, projects, components, insights, logs, notes, and quick actions within the LAIA Core environment. (Source: [3])

## Key facts

- The primary node is a Mac mini running OpenClaw via Docker and using Ollama for local inference with the llama3:latest model.
- Stable ports include OpenClaw UI on 18789, Tunnel UI on 18889, and Ollama on 11434.
- Active agents include Operator, Archivist, and others.
- The dashboard provides access to various systems like CRS - California Revival System, active work, focus mode projects, active projects, components, recent insights, logs, notes, and quick actions.

## Useful commands or paths

1. `docker compose restart openclaw-gateway` (Source: [2])
2. `curl -I http://127.0.0.1:18789/healthz` (Source: [2])
3. `ollama list` (Source: [2])

## Gaps / follow-up notes

While this packet provides a comprehensive overview of LAIA's Core and Dashboard, it does not detail the specific functions or purposes of each active agent, system, component, or quick action within the environment. Further investigation may be necessary to fully understand these elements and their roles in the LAIA Core ecosystem.

## Sources

### [1] LAIA Core Snapshot — OpenClaw Stable Baseline

- Score: `42`
- Path: `LAIA Core Snapshot — OpenClaw Stable Baseline.md`
- Type: `note`

#### Excerpt

# LAIA Core Snapshot — OpenClaw Stable Baseline Date: 2026-05-08 ## Runtime Status Gateway: healthy CLI: healthy Primary model: ollama/llama3:latest Reasoning: off OpenClaw Version: 2026.4.27 ## Stable Architecture Mac mini → Docker → OpenClaw → Ollama → SSH tunnel → Browser UI ## Stable Ports Gateway: 18789 Tunnel: 18889 Ollama: 11434 ## Workspace Files - AGENTS.md - MEMORY.md - USER.md - IDENTITY.md - TOOLS.md - HEARTBEAT.md - SOUL.md - BOOTSTRAP.md ## Active Agents - Operator - Archivist -...

### [2] LAIA Core Stable Baseline

- Score: `42`
- Path: `LAIA Core Stable Baseline.md`
- Type: `note`

#### Excerpt

# LAIA Core Stable Baseline ## Core Stack - Mac mini (primary node) - OpenClaw via Docker - Ollama local inference - llama3:latest primary model - SSH tunnel remote access ## Stable Ports - OpenClaw UI: 18789 - Tunnel UI: 18889 - Ollama: 11434 ## Rules - No new integrations until stable - Restart before debugging - One model change at a time - Memory and agents before automation ## Recovery Commands docker compose restart openclaw-gateway curl -I http://127.0.0.1:18789/healthz ollama list...

### [3] 🧠 LAIA CORE DASHBOARD

- Score: `36`
- Path: `00_DASHBOARD/LAIA_HOME.md`
- Type: `note`

#### Excerpt

# 🧠 LAIA CORE DASHBOARD ## 🏛️ Systems - [[CRS - California Revival System]] --- ## 📅 Today ## 🎯 Focus Today - --- ## 🟢 Active Work (Today) ## 🎯 Focus Mode (Projects Today) ## 🔥 Active Projects --- ## ⚙️ Systems --- ## 🧠 Recent Insights --- ## 📓 Recent Logs --- ## 🔩 Components --- ## ⚡ Quick Actions - Cmd + Shift + P → New Project - Cmd + Shift + S → New System - Cmd + Shift + C → New Component - Cmd + Shift + I → New Insight --- ## 🧭 Notes - Capture fast → process later - Promote ideas into the...

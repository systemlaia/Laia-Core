# LAIA Node Types

## Core Node
Primary machine: Mac mini

Responsibilities:
- host local models
- host Open WebUI
- host long-running services
- own master LAIA runtime
- own archives and reports
- perform reasoning, parsing, indexing, and automation

## Field Node
Primary machine: MacBook

Responsibilities:
- capture notes, tasks, meals, and voice input
- run lightweight CLI commands
- sync with core
- operate offline temporarily
- avoid heavy services and model hosting by default

## Design Rule
Default policy:
- field node captures
- core node thinks
- field node syncs
- core node processes

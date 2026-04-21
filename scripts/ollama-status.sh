#!/bin/bash

echo "=== LAIA OLLAMA STATUS ==="
echo
date
echo

echo "--- Installed models ---"
curl -s http://127.0.0.1:11434/api/tags | python3 -m json.tool
echo

echo "--- Running models ---"
curl -s http://127.0.0.1:11434/api/ps | python3 -m json.tool
echo

echo "--- Registry ---"
cat ~/LAIA-Core/models/registry.md
echo
# LAIA OpenClaw Baseline — 2026-05

Known-good target:
- OpenClaw gateway via Docker
- Gateway: http://127.0.0.1:18789
- Laptop tunnel: ssh -N -L 18889:127.0.0.1:18789 iv@Pauls-Mac-mini.local
- Browser: http://localhost:18889
- Primary model: ollama/llama3:latest

Health checks:
```bash
curl -I --max-time 5 http://127.0.0.1:18789/healthz
docker compose ps
ollama list

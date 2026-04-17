# LAIA Core Restore Notes

## 1. Fresh machine prep

- Install Docker Desktop
- Install Git
- Install VS Code
- Clone `LAIA-Core`
- Copy backup `.env.backup` to `.env`

## 2. Restore config

- Confirm compose files exist
- Confirm `caddy/`, `homepage/`, and `scripts/` were restored
- Confirm `Makefile` and `README.md` exist

## 3. Restore runtime data

Extract runtime backup from the repo root:

```bash
tar -xzf backups/<timestamp>/runtime-data.tgz
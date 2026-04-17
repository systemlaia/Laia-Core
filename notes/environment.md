# Environment Reference

## Purpose

The repo should be deployable from git with only one local secret file: `.env`.

## Required variables

### Homepage
- `HOMEPAGE_ALLOWED_HOSTS`
- used by: `docker-compose.ops.yml`
- purpose: allows homepage requests from approved host/port combinations

### Open WebUI
- `WEBUI_SECRET_KEY`
- used by: `docker-compose.ai.yml`
- purpose: application secret key

### Postgres
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- used by: `docker-compose.automation.yml`
- purpose: database credentials for postgres and n8n

### n8n
- `N8N_HOST`
- `N8N_PORT`
- `N8N_PROTOCOL`
- `WEBHOOK_URL`
- `N8N_ENCRYPTION_KEY`
- used by: `docker-compose.automation.yml`
- purpose: editor URL, webhook URL, and credential encryption

### Paperless / future layer
- `PAPERLESS_SECRET_KEY`
- `PAPERLESS_URL`
- used by: future docs stack

## Rules

1. Never commit `.env`
2. Commit `.env.example`
3. When adding a new variable:
   - add it to `.env.example`
   - document it here
   - reference it in the relevant compose file
4. Do not leave mystery variables undocumented
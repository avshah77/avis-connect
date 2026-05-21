# AVIS Connect — Claude Context

## Vault (read this first)
@/Volumes/Anytype/obs-vault/Claude/AVIS_Connect/_Index.md
@/Volumes/Anytype/obs-vault/Claude/AVIS_Connect/Journal/2026-05-18.md

## Project
Standalone FastAPI integration gateway — sits between AVIS client apps and external systems (NetSuite, Salesforce, Darwinbox).

- **Run:** `./runac` → starts on port 8001 (runs alembic then uvicorn --reload)
- **DB:** Shared Neon PostgreSQL, `connect.*` schema
- **Docs:** `http://localhost:8001/docs`

## Key files
- `app/routes/admin.py` — CRUD API + `_DEFAULT_OPS` (auto-seeded on new connector)
- `app/routes/ui.py` — Jinja2 routes + `_PLUGIN_META` (payload templates + credential keys)
- `app/routes/api.py` — `/api/execute`, `/api/retry`, Salesforce shortcut routes
- `app/core/engine.py` — 7-step execution flow
- `app/connectors/` — one .py per plugin (netsuite, salesforce, darwinbox)

## Active project in DB
- `rms-tessolve` (project_id=1) — NetSuite + Salesforce
- Salesforce connector_id=1, active operations: get_10_opportunities, get_opportunities, get_contacts, get_leads
- NetSuite connector_id=2, NS credentials still pending from Tessolve IT

## Open items
- NS credentials from Tessolve IT (blocked — target was 25-May-2026)
- Wire RMS3 → AVIS Connect via `POST /api/execute` once NS creds arrive
- Analytics dashboard (defer until real NS data flowing)
- Timesheet connector (spec in unread .msg email)

## Deployment
Currently on Render. Moving to AWS EC2 — both RMS3 (8000) and AVIS Connect (8001) will run as systemd services on same instance, talking via localhost.

## Session history
Memory files at: `~/.claude/projects/-Volumes-PYTHON-ROM_MVP-AVIS-Connect/memory/`
</content>

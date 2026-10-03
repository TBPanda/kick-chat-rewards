# Kick Chat Activity System

Collect Kick chat for one or more channels (starting with [amirphanthom](https://kick.com/amirphanthom)), store it in **Snowflake** (`KICK_CHAT.CORE`), query via **Snowflake Managed MCP**, and rank chatters with a **Streamlit** report.

## Stack

- **Python / FastAPI** — Kick webhook ingest + signature verification (multi-channel registry)
- **Snowflake** — `KICK_CHAT.CORE` shared tables + activity views
- **Streamlit** — password-gated leaderboard with channel picker + cross-channel user lookup
- **Snowflake Managed MCP** — one-off SQL from Cursor

## Repo layout

```
app/                 FastAPI webhook service
ingest/              config, channels registry, Kick signature, Snowflake writers
import_cli/          CSV/JSON historical import (no scraping)
sql/                 DDL, views, migration, MCP, row-access scaffolding
report/              Streamlit leaderboard
scripts/             apply SQL + Kick event subscribe helpers
mcp/                 Cursor mcp.json example
```

## Prerequisites

1. Snowflake account (warehouse + key pair recommended)
2. Kick Developer app at [kick.com/settings/developer](https://kick.com/settings/developer)
3. Public HTTPS URL for the webhook (Railway, etc.)

## Quick start

```bash
cd kick-chat-rewards
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env — set SNOWFLAKE_SCHEMA=CORE
```

### 1. Create Snowflake objects

```bash
python scripts/apply_sql.py
# If you already have legacy AMIRPHANTHOM data:
python scripts/apply_sql.py --migrate-legacy
```

Set Railway / `.env` `SNOWFLAKE_SCHEMA=CORE` after migration.

### 2. Run the webhook service

```bash
export PYTHONPATH=.
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health: `GET /health` · Webhook: `POST /webhooks/kick`

Webhooks are acknowledged immediately; Snowflake writes run on a background worker. A subscription watchdog re-subscribes if Kick drops `chat.message.sent`.

Events for channels **not** in `CHANNELS` are acknowledged but not stored.

### 3. Subscribe channels

```bash
python scripts/subscribe_kick_events.py --resolve-slug amirphanthom
python scripts/subscribe_kick_events.py --slug amirphanthom
# Multiple streamers on the same Kick app:
python scripts/subscribe_kick_events.py --slugs amirphanthom,otherstreamer
python scripts/subscribe_kick_events.py --list
```

Registers rows in `CHANNELS` and subscribes `chat.message.sent` + `livestream.status.updated`.

### 4. Reporting UI

```bash
PYTHONPATH=. streamlit run report/app.py
```

Pick a channel for leaderboards, or use **Cross-channel user** for involvement across channels.

### 5. Historical import

```bash
python -m import_cli.import_messages path/to/export.csv --dry-run
```

CSV: `message_id,kick_user_id,username,content,created_at` (optional `channel_slug`).

### 6. Cursor + Snowflake MCP

1. Ensure `KICK_CHAT_MCP` exists (`sql/003_mcp.sql`).
2. PAT for a role that can `SELECT` from `KICK_CHAT.CORE`.
3. Copy [mcp/cursor-mcp.json.example](mcp/cursor-mcp.json.example) into `~/.cursor/mcp.json`.
4. Prefer filtering by `CHANNEL_SLUG` in prompts.

## Data model (CORE)

| Object | Purpose |
|--------|---------|
| `TENANTS` | Org/tenant registry (default tenant for Phase 1) |
| `CHANNELS` | Tracked streamers + Kick subscription ids |
| `CHAT_MESSAGES` | One row per message (`MESSAGE_ID` PK) |
| `CHANNEL_USERS` | Per-channel chatter stats `PK(CHANNEL_SLUG, KICK_USER_ID)` |
| `STREAM_SESSIONS` | Live windows |
| `WEBHOOK_EVENTS` | Envelope idempotency |
| `LEADERBOARD_*` | Per-channel rankings |
| `USER_CHANNEL_ACTIVITY` / `USER_CROSS_CHANNEL_SUMMARY` | Cross-channel involvement |
| `TENANT_ROLE_MAP` | Scaffold for row access policies (`sql/006`) |

**Noise filter:** Kicklet promos dropped; Kicklet follow alerts kept.

## Multi-tenancy roadmap

- **Phase 1 (done in this schema):** shared `CORE` tables, channel registry, reject unknown channels, channel-scoped + cross-channel reports.
- **Phase 2:** enable `sql/006_row_access_policies.sql`, map streamer Snowflake users → `TENANT_ID`, add dashboard auth.

## Local tests

```bash
PYTHONPATH=. python tests/test_smoke.py
```

## Deploy

Railway: [DEPLOY_RAILWAY.md](DEPLOY_RAILWAY.md). After multi-channel merge, set `SNOWFLAKE_SCHEMA=CORE` and run `apply_sql.py` (+ `--migrate-legacy` if needed).

## Out of scope

- StreamerStats scraping
- Automatic Kick channel reward fulfillment
- Streamer self-serve signup / billing (Phase 2+)

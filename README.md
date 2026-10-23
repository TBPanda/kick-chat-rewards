# Kick Chat Activity System

Collect Kick chat for one or more channels (starting with [amirphanthom](https://kick.com/amirphanthom)), store it in **Postgres**, and rank chatters with a **Streamlit** report.

## Stack

- **Python / FastAPI** — Kick webhook ingest + signature verification (multi-channel registry)
- **Postgres** — Railway Postgres (shared tables + activity views)
- **Streamlit** — password-gated leaderboard with channel picker + cross-channel user lookup

## Repo layout

```
app/                 FastAPI webhook service
ingest/              config, channels registry, Kick signature, Postgres writers
import_cli/          CSV/JSON historical import (no scraping)
sql/                 Postgres DDL + views (legacy Snowflake under sql/legacy_snowflake/)
report/              Streamlit leaderboard
scripts/             apply SQL, Kick subscribe, Snowflake→Postgres migrate
```

## Prerequisites

1. Railway project (or any Postgres) + `DATABASE_URL`
2. Kick Developer app at [kick.com/settings/developer](https://kick.com/settings/developer)
3. Public HTTPS URL for the webhook (Railway, etc.)

## Quick start

```bash
cd kick-chat-rewards
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env — set DATABASE_URL
```

### 1. Create Postgres objects

```bash
python scripts/apply_sql.py
```

Migrating from Snowflake? See [CUTOVER.md](CUTOVER.md).

### 2. Run the webhook service

```bash
export PYTHONPATH=.
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health: `GET /health` · Webhook: `POST /webhooks/kick`

Webhooks are acknowledged immediately; Postgres writes run on a background worker. A subscription watchdog re-subscribes if Kick drops `chat.message.sent`.

Events for channels **not** in `channels` are acknowledged but not stored.

### 3. Subscribe channels

```bash
python scripts/subscribe_kick_events.py --resolve-slug amirphanthom
python scripts/subscribe_kick_events.py --slug amirphanthom
# Multiple streamers on the same Kick app:
python scripts/subscribe_kick_events.py --slugs amirphanthom,otherstreamer
python scripts/subscribe_kick_events.py --list
```

Registers rows in `channels` and subscribes `chat.message.sent` + `livestream.status.updated`.

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

## Data model

| Object | Purpose |
|--------|---------|
| `tenants` | Org/tenant registry (default tenant for Phase 1) |
| `channels` | Tracked streamers + Kick subscription ids |
| `chat_messages` | One row per message (`message_id` PK) |
| `channel_users` | Per-channel chatter stats `PK(channel_slug, kick_user_id)` |
| `stream_sessions` | Live windows |
| `webhook_events` | Envelope idempotency |
| `leaderboard_*` | Per-channel rankings |
| `user_channel_activity` / `user_cross_channel_summary` | Cross-channel involvement |

**Noise filter:** Kicklet promos dropped; Kicklet follow alerts kept.

## Local tests

```bash
PYTHONPATH=. python tests/test_smoke.py
```

## Deploy

Railway: [DEPLOY_RAILWAY.md](DEPLOY_RAILWAY.md).  
Leaving Snowflake: [CUTOVER.md](CUTOVER.md).

## Out of scope

- StreamerStats scraping
- Automatic Kick channel reward fulfillment
- Streamer self-serve signup / billing

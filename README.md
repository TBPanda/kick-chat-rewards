# Kick Chat Activity System — AmirPhanThom

Collect Kick chat for [amirphanthom](https://kick.com/amirphanthom), store it in **Snowflake**, query it via **Snowflake Managed MCP** in Cursor, and rank chatters with a small **Streamlit** report.

## Stack

- **Python / FastAPI** — Kick webhook ingest + signature verification
- **Snowflake** — `KICK_CHAT.AMIRPHANTHOM` tables + activity views
- **Streamlit** — password-gated leaderboard
- **Snowflake Managed MCP** — one-off SQL from Cursor (no custom MCP server)

JavaScript is intentionally not used for ingest/data. A friend can still build UI polish later if desired.

## Repo layout

```
app/                 FastAPI webhook service
ingest/              config, Kick signature verify, Snowflake writers
import_cli/          CSV/JSON historical import (no scraping)
sql/                 DDL, views, MCP server DDL
report/              Streamlit leaderboard
scripts/             apply SQL + Kick event subscribe helpers
mcp/                 Cursor mcp.json example
```

## Prerequisites

1. Snowflake account (warehouse + user/password or key pair — password used here)
2. Kick Developer app at [kick.com/settings/developer](https://kick.com/settings/developer)
3. Public HTTPS URL for the webhook (Fly.io, Railway, VPS, or Cloudflare Tunnel / ngrok for local)

## Quick start

```bash
cd kick-chat-rewards
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with Kick + Snowflake credentials
```

### 1. Create Snowflake objects

```bash
python scripts/apply_sql.py
```

This runs `sql/001_ddl.sql`, `002_views.sql`, and `003_mcp.sql`. If MCP creation fails (missing privilege), run `001`/`002` in the Snowflake UI and create the MCP server later as ACCOUNTADMIN.

### 2. Run the webhook service

```bash
export PYTHONPATH=.
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health check: `GET /health`  
Webhook: `POST /webhooks/kick`

Expose it publicly, then in the Kick Developer app:

- Enable Webhooks
- Set Webhook URL to `https://<your-host>/webhooks/kick`

### 3. Subscribe to AmirPhanThom events

Default broadcaster user id in `.env` is `538671` (verify with the resolve helper):

```bash
python scripts/subscribe_kick_events.py --resolve-slug amirphanthom
python scripts/subscribe_kick_events.py
python scripts/subscribe_kick_events.py --list
```

Subscribes to:

- `chat.message.sent`
- `livestream.status.updated`

Kick will unsubscribe if your endpoint fails for ~1 day — keep the service healthy and return **200** quickly.

### 4. Reporting UI

```bash
PYTHONPATH=. streamlit run report/app.py
```

Default password is `REPORT_PASSWORD` from `.env` (`changeme`).

### 5. Historical import (manual only)

**Do not scrape StreamerStats** — their ToS forbid bots/automated bulk access.

If you have a lawful CSV/JSON export:

```bash
python -m import_cli.import_messages import_cli/sample_messages.csv --dry-run
python -m import_cli.import_messages path/to/export.csv
```

CSV columns: `message_id,kick_user_id,username,content,created_at` (optional `channel_slug`).

### 6. Cursor + Snowflake MCP

1. Ensure `KICK_CHAT_MCP` exists (`sql/003_mcp.sql`).
2. Create a Snowflake Programmatic Access Token (PAT) for a role that can `SELECT` from `KICK_CHAT.AMIRPHANTHOM`.
3. Copy [mcp/cursor-mcp.json.example](mcp/cursor-mcp.json.example) into `~/.cursor/mcp.json` (merge with existing servers).
4. Replace `<ORG>-<ACCOUNT>` and the bearer token.
5. Restart Cursor / refresh MCP tools.

Example prompts once connected:

- Top 20 chatters last 30 days from `LEADERBOARD_30D`
- Users with 5+ `ACTIVE_STREAM_DAYS` from `STREAM_ACTIVE_DAYS`

## Data model

| Object | Purpose |
|--------|---------|
| `CHAT_MESSAGES` | One row per message (`MESSAGE_ID` PK, idempotent) |
| `USERS` | Chatter dimension |
| `STREAM_SESSIONS` | Live windows from status webhooks |
| `WEBHOOK_EVENTS` | Envelope idempotency / debug |
| `LEADERBOARD_*` | 7d / 30d / all-time rankings (excludes `!commands`) |
| `ACTIVITY_DAILY` | Per-user daily counts |
| `STREAM_ACTIVE_DAYS` | Unique stream-days active |

`SOURCE` is `webhook` or `import`.

**Noise filter:** messages from username `Kicklet` are not stored, except follow notifications (content matching follow/follower/فالو). Promo/tip ads from Kicklet are dropped at ingest so they do not hit Snowflake.

## Local tests (no cloud credentials)

```bash
PYTHONPATH=. python tests/test_smoke.py
```

## Deploy notes

**Target host:** Railway at `https://chat.amirphanthom.com` — see [DEPLOY_RAILWAY.md](DEPLOY_RAILWAY.md).

- Set `KICK_WEBHOOK_SKIP_VERIFY=false` in production.
- Restrict Streamlit with a strong `REPORT_PASSWORD` (or put it behind VPN/SSO later).
- Rotate Kick client secret and Snowflake PAT periodically.

## Out of scope

- StreamerStats scraping
- Automatic Kick channel reward fulfillment
- Multi-channel (add `CHANNEL_SLUG` filters when needed — column already present)

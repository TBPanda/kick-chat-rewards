# Deploy to Railway + chat.amirphanthom.com

## 1. Create / finish the Kick app (form values)

- Redirect URL: `https://chat.amirphanthom.com/oauth/callback`
- Enable Webhooks: **Off until deploy is healthy**, then On
- Webhook URL: `https://chat.amirphanthom.com/webhooks/kick`
- Scopes: keep **Read channel information** (skip channel-points for now)

Save **Client ID** and **Client Secret** for Railway variables.

## 2. Deploy this repo on Railway

1. Go to [railway.app](https://railway.app) → New Project → **Deploy from GitHub**  
   (push this repo first), **or** New Project → Empty Project → Add service → Docker.
2. Root directory = this project (`kick-chat-rewards`).
3. Builder should pick `Dockerfile` / `railway.toml`.
4. After first deploy, open the service → **Settings → Networking → Generate Domain**  
   (temporary `*.up.railway.app` URL). Confirm `https://YOUR.up.railway.app/health` returns `{"status":"ok"}`.

## 3. Add Railway Postgres

1. In the same project: **New** → **Database** → **PostgreSQL**.
2. Link it to the web/ingest service (or copy `DATABASE_URL` into that service’s Variables).
3. From your laptop (with `DATABASE_URL` in `.env`):

```bash
pip install -r requirements.txt
PYTHONPATH=. python scripts/apply_sql.py
PYTHONPATH=. python scripts/subscribe_kick_events.py --resolve-slug amirphanthom
PYTHONPATH=. python scripts/subscribe_kick_events.py
```

Migrating existing Snowflake data? Follow [CUTOVER.md](CUTOVER.md).

## 4. Environment variables (Railway → Variables)

```
KICK_CLIENT_ID=
KICK_CLIENT_SECRET=
KICK_BROADCASTER_USER_ID=538671
KICK_CHANNEL_SLUG=amirphanthom
KICK_WEBHOOK_SKIP_VERIFY=false

DATABASE_URL=   # from Railway Postgres (often auto-injected when linked)

REPORT_PASSWORD=
```

Do **not** set `SNOWFLAKE_*` on the running service after cutover.

## 5. Custom domain `chat.amirphanthom.com`

1. Railway service → **Settings → Networking → Custom Domain** → add `chat.amirphanthom.com`.
2. Railway shows a **CNAME** target.
3. In DNS for `amirphanthom.com`:

| Type  | Name  | Value                         | TTL  |
|-------|-------|-------------------------------|------|
| CNAME | chat  | *(value Railway shows you)*   | Auto |

4. Wait for Verified / SSL ready.
5. Test: `https://chat.amirphanthom.com/health` → `{"status":"ok"}`.

## 6. Turn on Kick webhooks

1. Kick Developer → Edit app → **Enable Webhooks: On**
2. Webhook URL: `https://chat.amirphanthom.com/webhooks/kick`
3. Save

## 7. Smoke test

- Someone sends a chat message in the tracked Kick channel.
- In Postgres: `SELECT * FROM chat_messages ORDER BY ingested_at DESC LIMIT 20;`

If nothing lands: check Railway logs for signature/Postgres errors, and `python scripts/subscribe_kick_events.py --list`.

The ingest service acks Kick immediately and writes Postgres on a background worker. A subscription watchdog (every `SUBSCRIPTION_WATCHDOG_INTERVAL_SEC`, default 120s) re-adds required events if Kick drops them. `GET /health` exposes worker queue depth and watchdog status.

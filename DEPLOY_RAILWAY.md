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

## 3. Environment variables (Railway → Variables)

Set at least:

```
KICK_CLIENT_ID=
KICK_CLIENT_SECRET=
KICK_BROADCASTER_USER_ID=538671
KICK_CHANNEL_SLUG=amirphanthom
KICK_WEBHOOK_SKIP_VERIFY=false

SNOWFLAKE_ACCOUNT=
SNOWFLAKE_USER=
SNOWFLAKE_PASSWORD=
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
SNOWFLAKE_DATABASE=KICK_CHAT
SNOWFLAKE_SCHEMA=AMIRPHANTHOM
SNOWFLAKE_ROLE=SYSADMIN

REPORT_PASSWORD=
```

Redeploy after saving vars. Snowflake can wait for a pure health-check test, but chat ingest will 500 without it — set Snowflake before enabling Kick webhooks.

## 4. Custom domain `chat.amirphanthom.com`

1. Railway service → **Settings → Networking → Custom Domain** → add `chat.amirphanthom.com`.
2. Railway shows a **CNAME** target (often `xxxx.up.railway.app` or a railway-provided host).
3. In your DNS for `amirphanthom.com` (wherever you bought it — Cloudflare, Namecheap, Google Domains, etc.):

| Type  | Name  | Value                         | TTL  |
|-------|-------|-------------------------------|------|
| CNAME | chat  | *(value Railway shows you)*   | Auto |

4. Wait for Railway to show the domain as **Verified** / SSL ready (can take a few minutes).
5. Test: `https://chat.amirphanthom.com/health` → `{"status":"ok"}`.

## 5. Turn on Kick webhooks

1. Kick Developer → Edit app → **Enable Webhooks: On**
2. Webhook URL: `https://chat.amirphanthom.com/webhooks/kick`
3. Save

## 6. Apply Snowflake SQL + subscribe events (from your laptop)

```bash
cd kick-chat-rewards
source .venv/bin/activate
cp .env.example .env   # fill same secrets as Railway
PYTHONPATH=. python scripts/apply_sql.py
PYTHONPATH=. python scripts/subscribe_kick_events.py --resolve-slug amirphanthom
PYTHONPATH=. python scripts/subscribe_kick_events.py
```

## 7. Smoke test

- Someone sends a chat message in AmirPhanThom’s Kick chat while live (or when chat is available).
- In Snowflake: `SELECT * FROM KICK_CHAT.AMIRPHANTHOM.CHAT_MESSAGES ORDER BY INGESTED_AT DESC LIMIT 20;`

If nothing lands: check Railway logs for signature/Snowflake errors, and `python scripts/subscribe_kick_events.py --list`.

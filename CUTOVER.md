# Manual cutover: Snowflake → Railway Postgres

Do these steps **after** the Postgres code is merged/deployed (or ready on your branch).

## 1. Add Postgres on Railway (you)

1. Open your Kick Chat project on [railway.app](https://railway.app).
2. **New** → **Database** → **PostgreSQL**.
3. Open the **Postgres** service → **Variables** → copy `DATABASE_URL`  
   (or **Connect** the Postgres service to your **web/ingest** service so Railway injects `DATABASE_URL` automatically).
4. On the **ingest/web** service → **Variables**:
   - Confirm `DATABASE_URL` is present.
   - Keep `KICK_*` and `REPORT_PASSWORD` as they are.
   - Leave `SNOWFLAKE_*` for now (remove in step 4).

## 2. Local `.env` (you)

```bash
cd kick-chat-rewards
source .venv/bin/activate
pip install -r requirements-migrate.txt
```

In `.env`:

- Set `DATABASE_URL` to the Railway Postgres URL (same as step 1).  
  Prefer the **public** URL if you run migrate from your laptop.
- Keep existing `SNOWFLAKE_*` values for the one-shot copy.

## 3. Schema + data migrate (you, laptop)

Storage-safe defaults (Railway ~5GB): skips `webhook_events` + `raw_payload`,
small batches, aborts if DB ≥ 4 GiB.

```bash
export PYTHONPATH=.
python scripts/apply_sql.py
python scripts/migrate_snowflake_to_postgres.py --dry-run
python scripts/migrate_snowflake_to_postgres.py \
  --batch-size 100 --sleep-ms 50 --max-db-gb 4.0
# If disk is high after a partial migrate:
python scripts/reclaim_postgres_space.py
```

Check that printed `snowflake=` and `postgres=` counts match for chat/users/sessions.

## 4. Point the app at Postgres only (you)

On Railway **ingest** service Variables:

1. Ensure `DATABASE_URL` is set.
2. **Delete** all `SNOWFLAKE_*` variables.
3. **Redeploy** the service.
4. Hit `https://chat.amirphanthom.com/health` → `status: ok`.
5. Send a Kick chat message → confirm a new row:

```bash
# from laptop, with DATABASE_URL set
psql "$DATABASE_URL" -c "SELECT message_id, username, content, created_at FROM chat_messages ORDER BY ingested_at DESC LIMIT 5;"
```

## 5. Stop Snowflake spend (you — important)

In **Snowsight** (worksheet):

```sql
ALTER WAREHOUSE COMPUTE_WH SUSPEND;
SHOW WAREHOUSES;
-- Suspend any other warehouses that are running.
```

When you’re happy with Postgres for a few days, cancel/delete the Snowflake account (or drop warehouses) so you are not billed again.

## 6. Optional cleanup

- Remove Snowflake MCP from `~/.cursor/mcp.json` if present.
- Locally you can drop commented `SNOWFLAKE_*` from `.env` after migrate succeeds.

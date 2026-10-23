# Kick Chat Activity — setup checklist
#
# Full Railway + chat.amirphanthom.com steps: see DEPLOY_RAILWAY.md
# Snowflake → Postgres cutover: see CUTOVER.md
#
# [ ] Create Kick Developer app (redirect https://chat.amirphanthom.com/oauth/callback)
# [ ] Deploy to Railway; custom domain chat.amirphanthom.com; GET /health OK
# [ ] Add Railway Postgres; set DATABASE_URL on the ingest service
# [ ] Set Railway env vars (KICK_* + DATABASE_URL + REPORT_PASSWORD)
# [ ] Enable Kick webhooks → https://chat.amirphanthom.com/webhooks/kick
# [ ] Copy .env.example → .env locally; fill same secrets
# [ ] python scripts/apply_sql.py
# [ ] If migrating from Snowflake: python scripts/migrate_snowflake_to_postgres.py
# [ ] python scripts/subscribe_kick_events.py --resolve-slug amirphanthom
# [ ] python scripts/subscribe_kick_events.py --slug amirphanthom
# [ ] Optional multi-channel: python scripts/subscribe_kick_events.py --slugs a,b
# [ ] Test chat message; SELECT * FROM chat_messages ORDER BY ingested_at DESC LIMIT 20;
# [ ] PYTHONPATH=. streamlit run report/app.py
# [ ] Suspend Snowflake warehouses (CUTOVER.md) so credits stop burning
# [ ] Optional: import lawful CSV via python -m import_cli.import_messages ...

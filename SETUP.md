# Kick Chat Activity — setup checklist
#
# Full Railway + chat.amirphanthom.com steps: see DEPLOY_RAILWAY.md
#
# [ ] Create Kick Developer app (redirect https://chat.amirphanthom.com/oauth/callback)
# [ ] Deploy to Railway; custom domain chat.amirphanthom.com; GET /health OK
# [ ] Set Railway env vars (KICK_* + SNOWFLAKE_*)
# [ ] Enable Kick webhooks → https://chat.amirphanthom.com/webhooks/kick
# [ ] Copy .env.example → .env locally; fill same secrets
# [ ] python scripts/apply_sql.py
# [ ] python scripts/subscribe_kick_events.py --resolve-slug amirphanthom
# [ ] python scripts/subscribe_kick_events.py
# [ ] Test chat message; check CHAT_MESSAGES in Snowflake
# [ ] PYTHONPATH=. streamlit run report/app.py
# [ ] Wire mcp/cursor-mcp.json.example into ~/.cursor/mcp.json
# [ ] Optional: import lawful CSV via python -m import_cli.import_messages ...

-- Snowflake Managed MCP server for Cursor (multi-channel CORE schema)
-- Requires a role that can CREATE MCP SERVER (often ACCOUNTADMIN).

USE DATABASE KICK_CHAT;
USE SCHEMA CORE;

-- Grant the ingest/reporting role usage on objects as needed before wiring MCP.
-- Example (uncomment and edit role name):
-- GRANT USAGE ON DATABASE KICK_CHAT TO ROLE KICK_CHAT_ROLE;
-- GRANT USAGE ON SCHEMA KICK_CHAT.CORE TO ROLE KICK_CHAT_ROLE;
-- GRANT SELECT ON ALL TABLES IN SCHEMA KICK_CHAT.CORE TO ROLE KICK_CHAT_ROLE;
-- GRANT SELECT ON ALL VIEWS IN SCHEMA KICK_CHAT.CORE TO ROLE KICK_CHAT_ROLE;

CREATE OR REPLACE MCP SERVER KICK_CHAT_MCP
  FROM SPECIFICATION $$
    tools:
      - name: "execute_sql"
        type: "SYSTEM_EXECUTE_SQL"
        title: "Kick Chat SQL"
        description: >
          Run read SQL against KICK_CHAT.CORE for multi-channel Kick chat
          activity. Always filter by CHANNEL_SLUG for per-streamer reports.
          Prefer views LEADERBOARD_7D, LEADERBOARD_30D, LEADERBOARD_ALL_TIME,
          ACTIVITY_DAILY, STREAM_ACTIVE_DAYS, ACTIVITY_BY_STREAM,
          USER_CHANNEL_ACTIVITY, USER_CROSS_CHANNEL_SUMMARY.
          Tables: CHANNELS, CHAT_MESSAGES, CHANNEL_USERS, STREAM_SESSIONS, TENANTS.
  $$;

-- After creation, wire Cursor ~/.cursor/mcp.json (see mcp/cursor-mcp.json.example).
-- MCP URL shape:
--   https://<ORG>-<ACCOUNT>.snowflakecomputing.com/api/v2/databases/KICK_CHAT/schemas/CORE/mcp-servers/KICK_CHAT_MCP
--
-- Auth: Programmatic Access Token (PAT) or OAuth client credentials as documented by Snowflake.
-- Multi-tenant: see sql/006_row_access_policies.sql before exposing MCP to streamers.

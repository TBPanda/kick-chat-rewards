-- Snowflake Managed MCP server for Cursor one-off queries
-- Requires a role that can CREATE MCP SERVER (often ACCOUNTADMIN).
-- Adjust database/schema/name to match your account.

USE DATABASE KICK_CHAT;
USE SCHEMA AMIRPHANTHOM;

-- Grant the ingest/reporting role usage on objects as needed before wiring MCP.
-- Example (uncomment and edit role name):
-- GRANT USAGE ON DATABASE KICK_CHAT TO ROLE KICK_CHAT_ROLE;
-- GRANT USAGE ON SCHEMA KICK_CHAT.AMIRPHANTHOM TO ROLE KICK_CHAT_ROLE;
-- GRANT SELECT ON ALL TABLES IN SCHEMA KICK_CHAT.AMIRPHANTHOM TO ROLE KICK_CHAT_ROLE;
-- GRANT SELECT ON ALL VIEWS IN SCHEMA KICK_CHAT.AMIRPHANTHOM TO ROLE KICK_CHAT_ROLE;

CREATE OR REPLACE MCP SERVER KICK_CHAT_MCP
  FROM SPECIFICATION $$
    tools:
      - name: "execute_sql"
        type: "SYSTEM_EXECUTE_SQL"
        title: "Kick Chat SQL"
        description: >
          Run read SQL against KICK_CHAT.AMIRPHANTHOM for AmirPhanThom chat
          activity. Prefer views LEADERBOARD_7D, LEADERBOARD_30D,
          LEADERBOARD_ALL_TIME, ACTIVITY_DAILY, STREAM_ACTIVE_DAYS,
          ACTIVITY_BY_STREAM. Tables: CHAT_MESSAGES, USERS, STREAM_SESSIONS.
  $$;

-- After creation, wire Cursor ~/.cursor/mcp.json (see mcp/cursor-mcp.json.example).
-- MCP URL shape:
--   https://<ORG>-<ACCOUNT>.snowflakecomputing.com/api/v2/databases/KICK_CHAT/schemas/AMIRPHANTHOM/mcp-servers/KICK_CHAT_MCP
--
-- Auth: Programmatic Access Token (PAT) or OAuth client credentials as documented by Snowflake.

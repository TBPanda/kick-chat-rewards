-- Phase 2: multi-tenant row access policies (scaffolding)
-- Apply only when streamers get their own Snowflake roles / dashboards.
-- Until then, operator roles may SELECT the full CORE schema.
--
-- Pattern: session variable CURRENT_TENANT_ID set at login (or use
-- Snowflake mapping via CURRENT_USER() → tenant). Policies join CHANNELS
-- so fact tables stay CHANNEL_SLUG-keyed without denormalizing TENANT_ID.

USE DATABASE KICK_CHAT;
USE SCHEMA CORE;

-- Example mapping table: Snowflake login name → tenant
CREATE TABLE IF NOT EXISTS TENANT_ROLE_MAP (
    SNOWFLAKE_USER      VARCHAR(256)    NOT NULL,
    TENANT_ID           VARCHAR(64)     NOT NULL,
    CONSTRAINT PK_TENANT_ROLE_MAP PRIMARY KEY (SNOWFLAKE_USER)
);

-- Uncomment and adapt when enabling per-tenant isolation:
--
-- CREATE OR REPLACE ROW ACCESS POLICY RAP_CHANNEL_TENANT
-- AS (CHANNEL_SLUG VARCHAR) RETURNS BOOLEAN ->
--   EXISTS (
--     SELECT 1
--     FROM CHANNELS c
--     JOIN TENANT_ROLE_MAP m ON m.TENANT_ID = c.TENANT_ID
--     WHERE c.CHANNEL_SLUG = CHANNEL_SLUG
--       AND UPPER(m.SNOWFLAKE_USER) = UPPER(CURRENT_USER())
--   )
--   OR EXISTS (
--     SELECT 1 FROM TENANT_ROLE_MAP m
--     WHERE m.TENANT_ID = 'default'
--       AND UPPER(m.SNOWFLAKE_USER) = UPPER(CURRENT_USER())
--   );
--
-- ALTER TABLE CHAT_MESSAGES ADD ROW ACCESS POLICY RAP_CHANNEL_TENANT ON (CHANNEL_SLUG);
-- ALTER TABLE CHANNEL_USERS ADD ROW ACCESS POLICY RAP_CHANNEL_TENANT ON (CHANNEL_SLUG);
-- ALTER TABLE STREAM_SESSIONS ADD ROW ACCESS POLICY RAP_CHANNEL_TENANT ON (CHANNEL_SLUG);
-- ALTER TABLE CHANNELS ADD ROW ACCESS POLICY RAP_CHANNEL_TENANT ON (CHANNEL_SLUG);
--
-- Auth for Streamlit / future streamer dashboards should set the Snowflake
-- session user (or bind TENANT_ID) so policies apply. Operator MCP PATs should
-- map to TENANT_ID='default' (full visibility) or a specific tenant.

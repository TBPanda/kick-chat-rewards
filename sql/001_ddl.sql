-- Kick Chat Activity System — Postgres schema
-- Applied via: python scripts/apply_sql.py
-- Requires DATABASE_URL (Railway Postgres or local).

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id       VARCHAR(64)     NOT NULL,
    display_name    VARCHAR(256),
    status          VARCHAR(32)     NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_tenants PRIMARY KEY (tenant_id)
);

INSERT INTO tenants (tenant_id, display_name)
VALUES ('default', 'Default operator')
ON CONFLICT (tenant_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS channels (
    channel_slug                VARCHAR(128)    NOT NULL,
    tenant_id                   VARCHAR(64)     NOT NULL DEFAULT 'default',
    broadcaster_user_id         BIGINT,
    display_name                VARCHAR(256),
    status                      VARCHAR(32)     NOT NULL DEFAULT 'active',
    chat_subscription_id        VARCHAR(128),
    livestream_subscription_id  VARCHAR(128),
    created_at                  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_channels PRIMARY KEY (channel_slug),
    CONSTRAINT fk_channels_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id          VARCHAR(128)    NOT NULL,
    event_message_id    VARCHAR(128),
    channel_slug        VARCHAR(128)    NOT NULL,
    broadcaster_user_id BIGINT,
    kick_user_id        BIGINT          NOT NULL,
    username            VARCHAR(256)    NOT NULL,
    content             VARCHAR(8192),
    created_at          TIMESTAMPTZ     NOT NULL,
    source              VARCHAR(32)     NOT NULL DEFAULT 'webhook',
    is_command          BOOLEAN         DEFAULT FALSE,
    raw_payload         JSONB,
    ingested_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_chat_messages PRIMARY KEY (message_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_channel_created
    ON chat_messages (channel_slug, created_at);

CREATE INDEX IF NOT EXISTS idx_chat_messages_user
    ON chat_messages (kick_user_id, created_at);

CREATE TABLE IF NOT EXISTS channel_users (
    channel_slug        VARCHAR(128)    NOT NULL,
    kick_user_id        BIGINT          NOT NULL,
    username            VARCHAR(256)    NOT NULL,
    profile_picture     VARCHAR(1024),
    is_verified         BOOLEAN         DEFAULT FALSE,
    first_seen_at       TIMESTAMPTZ     NOT NULL,
    last_seen_at        TIMESTAMPTZ     NOT NULL,
    message_count       BIGINT          DEFAULT 0,
    CONSTRAINT pk_channel_users PRIMARY KEY (channel_slug, kick_user_id)
);

CREATE TABLE IF NOT EXISTS stream_sessions (
    session_id          VARCHAR(128)    NOT NULL,
    channel_slug        VARCHAR(128)    NOT NULL,
    broadcaster_user_id BIGINT,
    title               VARCHAR(1024),
    started_at          TIMESTAMPTZ     NOT NULL,
    ended_at            TIMESTAMPTZ,
    is_live             BOOLEAN         NOT NULL DEFAULT TRUE,
    raw_payload         JSONB,
    ingested_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_stream_sessions PRIMARY KEY (session_id)
);

CREATE INDEX IF NOT EXISTS idx_stream_sessions_channel_started
    ON stream_sessions (channel_slug, started_at);

CREATE TABLE IF NOT EXISTS webhook_events (
    event_message_id    VARCHAR(128)    NOT NULL,
    event_type          VARCHAR(128)    NOT NULL,
    event_version       VARCHAR(16),
    subscription_id     VARCHAR(128),
    channel_slug        VARCHAR(128),
    received_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    processed_ok        BOOLEAN         DEFAULT TRUE,
    error_message       VARCHAR(2048),
    CONSTRAINT pk_webhook_events PRIMARY KEY (event_message_id)
);

-- Seed first channel if missing (safe for fresh deploys)
INSERT INTO channels (
    channel_slug, tenant_id, broadcaster_user_id, display_name
) VALUES (
    'amirphanthom', 'default', 538671, 'AmirPhanThom'
)
ON CONFLICT (channel_slug) DO NOTHING;

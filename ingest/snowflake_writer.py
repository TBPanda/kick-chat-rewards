"""Snowflake connection and idempotent writers for chat + stream events."""

from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import uuid4

import snowflake.connector
from cryptography.hazmat.primitives import serialization
from snowflake.connector import DictCursor

from ingest.config import Settings, get_settings

logger = logging.getLogger(__name__)

COMMAND_RE = re.compile(r"^!\S+")
# Kicklet posts recurring promo/tip ads; keep only follow alerts from that bot.
KICKLET_USERNAMES = frozenset({"kicklet"})
KICKLET_FOLLOW_RE = re.compile(
    r"(?:\bfollow(?:ed|ing|er)?\b|\bnew\s+follower\b|"
    r"\u0641\u0627\u0644\u0648|"  # فالو (Persian "follow")
    r"\u0641\u0627\u0644\u0648\u0631)",  # فالور
    re.IGNORECASE,
)


def is_command_message(content: str | None) -> bool:
    if not content:
        return False
    return bool(COMMAND_RE.match(content.strip()))


def is_kicklet_sender(username: str | None) -> bool:
    if not username:
        return False
    # Kick may send "Kicklet" or "@Kicklet"
    normalized = username.strip().lstrip("@").lower()
    return normalized in KICKLET_USERNAMES


def is_kicklet_follow_notification(content: str | None) -> bool:
    """True when Kicklet content looks like a follow alert (worth keeping)."""
    if not content:
        return False
    return bool(KICKLET_FOLLOW_RE.search(content))


def should_skip_chat_message(username: str | None, content: str | None) -> bool:
    """
    Drop Kicklet promotional spam; keep Kicklet follow notifications and all
    other senders.
    """
    if not is_kicklet_sender(username):
        return False
    return not is_kicklet_follow_notification(content)


def _load_private_key_bytes(pem: str, passphrase: str | None) -> bytes:
    """Load PEM private key and return DER bytes for snowflake-connector."""
    # Support Railway env values that use literal \n instead of real newlines
    normalized = pem.strip().replace("\\n", "\n")
    password = passphrase.encode("utf-8") if passphrase else None
    key = serialization.load_pem_private_key(
        normalized.encode("utf-8"),
        password=password,
    )
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@contextmanager
def snowflake_connection(settings: Settings | None = None) -> Iterator[Any]:
    s = settings or get_settings()
    if not s.snowflake_account or not s.snowflake_user:
        raise RuntimeError(
            "Snowflake credentials missing. Set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, "
            "and either SNOWFLAKE_PRIVATE_KEY (recommended) or SNOWFLAKE_PASSWORD."
        )

    connect_kwargs: dict[str, Any] = {
        "account": s.snowflake_account,
        "user": s.snowflake_user,
        "warehouse": s.snowflake_warehouse,
        "database": s.snowflake_database,
        "schema": s.snowflake_schema,
        "role": s.snowflake_role,
    }

    if s.snowflake_private_key.strip():
        connect_kwargs["private_key"] = _load_private_key_bytes(
            s.snowflake_private_key,
            s.snowflake_private_key_passphrase or None,
        )
    elif s.snowflake_password:
        connect_kwargs["password"] = s.snowflake_password
    else:
        raise RuntimeError(
            "Set SNOWFLAKE_PRIVATE_KEY (recommended; avoids MFA) "
            "or SNOWFLAKE_PASSWORD in the environment."
        )

    conn = snowflake.connector.connect(**connect_kwargs)
    try:
        yield conn
    finally:
        conn.close()


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    # Kick sends RFC3339 / ISO-8601
    cleaned = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return datetime.now(timezone.utc)


def record_webhook_event(
    conn: Any,
    *,
    event_message_id: str,
    event_type: str,
    event_version: str | None,
    subscription_id: str | None,
    processed_ok: bool = True,
    error_message: str | None = None,
    channel_slug: str | None = None,
) -> bool:
    """
    Insert webhook envelope. Returns False if this event_message_id was already seen
    (duplicate delivery).
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """
            MERGE INTO WEBHOOK_EVENTS t
            USING (
                SELECT
                    %s AS EVENT_MESSAGE_ID,
                    %s AS EVENT_TYPE,
                    %s AS EVENT_VERSION,
                    %s AS SUBSCRIPTION_ID,
                    %s AS CHANNEL_SLUG,
                    %s AS PROCESSED_OK,
                    %s AS ERROR_MESSAGE
            ) s
            ON t.EVENT_MESSAGE_ID = s.EVENT_MESSAGE_ID
            WHEN NOT MATCHED THEN INSERT (
                EVENT_MESSAGE_ID, EVENT_TYPE, EVENT_VERSION, SUBSCRIPTION_ID,
                CHANNEL_SLUG, PROCESSED_OK, ERROR_MESSAGE
            ) VALUES (
                s.EVENT_MESSAGE_ID, s.EVENT_TYPE, s.EVENT_VERSION, s.SUBSCRIPTION_ID,
                s.CHANNEL_SLUG, s.PROCESSED_OK, s.ERROR_MESSAGE
            )
            """,
            (
                event_message_id,
                event_type,
                event_version,
                subscription_id,
                channel_slug,
                processed_ok,
                error_message,
            ),
        )
        # rowcount 1 = inserted; 0 = already existed
        return cur.rowcount == 1
    finally:
        cur.close()


def upsert_channel_user(
    conn: Any,
    *,
    kick_user_id: int,
    username: str,
    channel_slug: str,
    profile_picture: str | None,
    is_verified: bool,
    seen_at: datetime,
) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            MERGE INTO CHANNEL_USERS t
            USING (
                SELECT
                    %s AS CHANNEL_SLUG,
                    %s AS KICK_USER_ID,
                    %s AS USERNAME,
                    %s AS PROFILE_PICTURE,
                    %s AS IS_VERIFIED,
                    %s AS SEEN_AT
            ) s
            ON t.CHANNEL_SLUG = s.CHANNEL_SLUG AND t.KICK_USER_ID = s.KICK_USER_ID
            WHEN MATCHED THEN UPDATE SET
                USERNAME = s.USERNAME,
                PROFILE_PICTURE = COALESCE(s.PROFILE_PICTURE, t.PROFILE_PICTURE),
                IS_VERIFIED = s.IS_VERIFIED,
                LAST_SEEN_AT = GREATEST(t.LAST_SEEN_AT, s.SEEN_AT),
                MESSAGE_COUNT = t.MESSAGE_COUNT + 1
            WHEN NOT MATCHED THEN INSERT (
                CHANNEL_SLUG, KICK_USER_ID, USERNAME, PROFILE_PICTURE, IS_VERIFIED,
                FIRST_SEEN_AT, LAST_SEEN_AT, MESSAGE_COUNT
            ) VALUES (
                s.CHANNEL_SLUG, s.KICK_USER_ID, s.USERNAME, s.PROFILE_PICTURE, s.IS_VERIFIED,
                s.SEEN_AT, s.SEEN_AT, 1
            )
            """,
            (
                channel_slug,
                kick_user_id,
                username,
                profile_picture,
                is_verified,
                seen_at,
            ),
        )
    finally:
        cur.close()


# Back-compat alias for imports that still say upsert_user
def upsert_user(
    conn: Any,
    *,
    kick_user_id: int,
    username: str,
    channel_slug: str | None,
    profile_picture: str | None,
    is_verified: bool,
    seen_at: datetime,
) -> None:
    if not channel_slug:
        raise ValueError("channel_slug is required for CHANNEL_USERS upsert")
    upsert_channel_user(
        conn,
        kick_user_id=kick_user_id,
        username=username,
        channel_slug=channel_slug,
        profile_picture=profile_picture,
        is_verified=is_verified,
        seen_at=seen_at,
    )


def insert_chat_message(
    conn: Any,
    *,
    message_id: str,
    event_message_id: str | None,
    channel_slug: str,
    broadcaster_user_id: int | None,
    kick_user_id: int,
    username: str,
    content: str | None,
    created_at: datetime,
    source: str,
    raw_payload: dict[str, Any] | None,
) -> bool:
    """Insert chat message. Returns True if inserted, False if duplicate message_id."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            MERGE INTO CHAT_MESSAGES t
            USING (
                SELECT
                    %s AS MESSAGE_ID,
                    %s AS EVENT_MESSAGE_ID,
                    %s AS CHANNEL_SLUG,
                    %s AS BROADCASTER_USER_ID,
                    %s AS KICK_USER_ID,
                    %s AS USERNAME,
                    %s AS CONTENT,
                    %s AS CREATED_AT,
                    %s AS SOURCE,
                    %s AS IS_COMMAND,
                    PARSE_JSON(%s) AS RAW_PAYLOAD
            ) s
            ON t.MESSAGE_ID = s.MESSAGE_ID
            WHEN NOT MATCHED THEN INSERT (
                MESSAGE_ID, EVENT_MESSAGE_ID, CHANNEL_SLUG, BROADCASTER_USER_ID,
                KICK_USER_ID, USERNAME, CONTENT, CREATED_AT, SOURCE, IS_COMMAND, RAW_PAYLOAD
            ) VALUES (
                s.MESSAGE_ID, s.EVENT_MESSAGE_ID, s.CHANNEL_SLUG, s.BROADCASTER_USER_ID,
                s.KICK_USER_ID, s.USERNAME, s.CONTENT, s.CREATED_AT, s.SOURCE,
                s.IS_COMMAND, s.RAW_PAYLOAD
            )
            """,
            (
                message_id,
                event_message_id,
                channel_slug,
                broadcaster_user_id,
                kick_user_id,
                username,
                content,
                created_at,
                source,
                is_command_message(content),
                json.dumps(raw_payload) if raw_payload is not None else None,
            ),
        )
        return cur.rowcount == 1
    finally:
        cur.close()


def handle_chat_message_sent(
    conn: Any,
    payload: dict[str, Any],
    *,
    event_message_id: str | None,
    channel_slug: str,
    source: str = "webhook",
) -> bool:
    sender = payload.get("sender") or {}
    broadcaster = payload.get("broadcaster") or {}
    message_id = payload.get("message_id")
    if not message_id:
        raise ValueError("chat.message.sent missing message_id")

    kick_user_id = sender.get("user_id")
    username = sender.get("username") or "unknown"
    if kick_user_id is None:
        raise ValueError("chat.message.sent missing sender.user_id")

    created_at = _parse_ts(payload.get("created_at"))
    content = payload.get("content")
    if should_skip_chat_message(str(username), content):
        logger.info(
            "Skipping Kicklet promo message %s from %s",
            message_id,
            username,
        )
        return False

    bc_id = broadcaster.get("user_id")
    slug = (
        broadcaster.get("channel_slug")
        or channel_slug
    )

    inserted = insert_chat_message(
        conn,
        message_id=str(message_id),
        event_message_id=event_message_id,
        channel_slug=slug,
        broadcaster_user_id=int(bc_id) if bc_id is not None else None,
        kick_user_id=int(kick_user_id),
        username=str(username),
        content=content,
        created_at=created_at,
        source=source,
        raw_payload=payload,
    )
    if inserted:
        upsert_channel_user(
            conn,
            kick_user_id=int(kick_user_id),
            username=str(username),
            channel_slug=str(slug),
            profile_picture=sender.get("profile_picture"),
            is_verified=bool(sender.get("is_verified")),
            seen_at=created_at,
        )
        logger.info(
            "Stored chat message %s channel=%s user=%s",
            message_id,
            slug,
            username,
        )
    else:
        logger.info("Duplicate chat message_id %s — skipped insert", message_id)
    return inserted


def handle_livestream_status(
    conn: Any,
    payload: dict[str, Any],
    *,
    channel_slug: str,
) -> str:
    """Upsert stream session. Returns session_id."""
    broadcaster = payload.get("broadcaster") or {}
    is_live = bool(payload.get("is_live"))
    started_at = _parse_ts(payload.get("started_at"))
    ended_at = _parse_ts(payload.get("ended_at")) if payload.get("ended_at") else None
    title = payload.get("title")
    bc_id = broadcaster.get("user_id")
    slug = broadcaster.get("channel_slug") or channel_slug

    # Stable session id from started_at + broadcaster when available
    session_id = f"{slug}:{started_at.isoformat()}"
    if not payload.get("started_at"):
        session_id = str(uuid4())

    cur = conn.cursor()
    try:
        if is_live:
            cur.execute(
                """
                MERGE INTO STREAM_SESSIONS t
                USING (
                    SELECT
                        %s AS SESSION_ID,
                        %s AS CHANNEL_SLUG,
                        %s AS BROADCASTER_USER_ID,
                        %s AS TITLE,
                        %s AS STARTED_AT,
                        PARSE_JSON(%s) AS RAW_PAYLOAD
                ) s
                ON t.SESSION_ID = s.SESSION_ID
                WHEN MATCHED THEN UPDATE SET
                    TITLE = COALESCE(s.TITLE, t.TITLE),
                    IS_LIVE = TRUE,
                    ENDED_AT = NULL,
                    RAW_PAYLOAD = s.RAW_PAYLOAD
                WHEN NOT MATCHED THEN INSERT (
                    SESSION_ID, CHANNEL_SLUG, BROADCASTER_USER_ID, TITLE,
                    STARTED_AT, ENDED_AT, IS_LIVE, RAW_PAYLOAD
                ) VALUES (
                    s.SESSION_ID, s.CHANNEL_SLUG, s.BROADCASTER_USER_ID, s.TITLE,
                    s.STARTED_AT, NULL, TRUE, s.RAW_PAYLOAD
                )
                """,
                (
                    session_id,
                    slug,
                    int(bc_id) if bc_id is not None else None,
                    title,
                    started_at,
                    json.dumps(payload),
                ),
            )
        else:
            # End the open session matching started_at, or create closed row
            cur.execute(
                """
                MERGE INTO STREAM_SESSIONS t
                USING (
                    SELECT
                        %s AS SESSION_ID,
                        %s AS CHANNEL_SLUG,
                        %s AS BROADCASTER_USER_ID,
                        %s AS TITLE,
                        %s AS STARTED_AT,
                        %s AS ENDED_AT,
                        PARSE_JSON(%s) AS RAW_PAYLOAD
                ) s
                ON t.SESSION_ID = s.SESSION_ID
                WHEN MATCHED THEN UPDATE SET
                    IS_LIVE = FALSE,
                    ENDED_AT = COALESCE(s.ENDED_AT, CURRENT_TIMESTAMP()),
                    TITLE = COALESCE(s.TITLE, t.TITLE),
                    RAW_PAYLOAD = s.RAW_PAYLOAD
                WHEN NOT MATCHED THEN INSERT (
                    SESSION_ID, CHANNEL_SLUG, BROADCASTER_USER_ID, TITLE,
                    STARTED_AT, ENDED_AT, IS_LIVE, RAW_PAYLOAD
                ) VALUES (
                    s.SESSION_ID, s.CHANNEL_SLUG, s.BROADCASTER_USER_ID, s.TITLE,
                    s.STARTED_AT, s.ENDED_AT, FALSE, s.RAW_PAYLOAD
                )
                """,
                (
                    session_id,
                    slug,
                    int(bc_id) if bc_id is not None else None,
                    title,
                    started_at,
                    ended_at,
                    json.dumps(payload),
                ),
            )
    finally:
        cur.close()
    return session_id


def query_leaderboard(
    conn: Any,
    *,
    channel_slug: str,
    days: int | None = 30,
    limit: int = 50,
    exclude_commands: bool = True,
) -> list[dict[str, Any]]:
    where = ["CHANNEL_SLUG = %s"]
    params: list[Any] = [channel_slug]
    if exclude_commands:
        where.append("NOT COALESCE(IS_COMMAND, FALSE)")
    if days is not None:
        where.append("CREATED_AT >= DATEADD('DAY', %s, CURRENT_TIMESTAMP())")
        params.append(-days)
    where_sql = "WHERE " + " AND ".join(where)
    params.append(limit)
    sql = f"""
        SELECT
            CHANNEL_SLUG,
            KICK_USER_ID,
            MAX(USERNAME) AS USERNAME,
            COUNT(*) AS MESSAGE_COUNT,
            COUNT(DISTINCT DATE_TRUNC('DAY', CREATED_AT)::DATE) AS ACTIVE_DAYS,
            MIN(CREATED_AT) AS FIRST_MESSAGE_AT,
            MAX(CREATED_AT) AS LAST_MESSAGE_AT
        FROM CHAT_MESSAGES
        {where_sql}
        GROUP BY CHANNEL_SLUG, KICK_USER_ID
        ORDER BY MESSAGE_COUNT DESC
        LIMIT %s
    """
    cur = conn.cursor(DictCursor)
    try:
        cur.execute(sql, params)
        return list(cur.fetchall())
    finally:
        cur.close()


def query_user_messages(
    conn: Any,
    *,
    kick_user_id: int,
    channel_slug: str | None = None,
    days: int | None = 30,
    limit: int = 200,
) -> list[dict[str, Any]]:
    params: list[Any] = [kick_user_id]
    extras = ["KICK_USER_ID = %s"]
    if channel_slug:
        extras.append("CHANNEL_SLUG = %s")
        params.append(channel_slug)
    if days is not None:
        extras.append("CREATED_AT >= DATEADD('DAY', %s, CURRENT_TIMESTAMP())")
        params.append(-days)
    params.append(limit)
    where_sql = " AND ".join(extras)
    cur = conn.cursor(DictCursor)
    try:
        cur.execute(
            f"""
            SELECT MESSAGE_ID, CHANNEL_SLUG, USERNAME, CONTENT, CREATED_AT, SOURCE, IS_COMMAND
            FROM CHAT_MESSAGES
            WHERE {where_sql}
            ORDER BY CREATED_AT DESC
            LIMIT %s
            """,
            params,
        )
        return list(cur.fetchall())
    finally:
        cur.close()


def query_user_cross_channel(
    conn: Any,
    *,
    kick_user_id: int | None = None,
    username: str | None = None,
    days: int | None = 30,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Operator view: one Kick user's activity broken down by channel."""
    where = ["NOT COALESCE(IS_COMMAND, FALSE)"]
    params: list[Any] = []
    if kick_user_id is not None:
        where.append("KICK_USER_ID = %s")
        params.append(kick_user_id)
    if username:
        where.append("LOWER(USERNAME) = LOWER(%s)")
        params.append(username)
    if days is not None:
        where.append("CREATED_AT >= DATEADD('DAY', %s, CURRENT_TIMESTAMP())")
        params.append(-days)
    if kick_user_id is None and not username:
        raise ValueError("Provide kick_user_id or username")
    params.append(limit)
    where_sql = " AND ".join(where)
    cur = conn.cursor(DictCursor)
    try:
        cur.execute(
            f"""
            SELECT
                KICK_USER_ID,
                MAX(USERNAME) AS USERNAME,
                CHANNEL_SLUG,
                COUNT(*) AS MESSAGE_COUNT,
                COUNT(DISTINCT DATE_TRUNC('DAY', CREATED_AT)::DATE) AS ACTIVE_DAYS,
                MIN(CREATED_AT) AS FIRST_MESSAGE_AT,
                MAX(CREATED_AT) AS LAST_MESSAGE_AT
            FROM CHAT_MESSAGES
            WHERE {where_sql}
            GROUP BY KICK_USER_ID, CHANNEL_SLUG
            ORDER BY MESSAGE_COUNT DESC
            LIMIT %s
            """,
            params,
        )
        return list(cur.fetchall())
    finally:
        cur.close()

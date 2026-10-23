"""Postgres connection and idempotent writers for chat + stream events."""

from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

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


def open_connection(settings: Settings | None = None) -> psycopg.Connection:
    """Open a Postgres connection (caller must close)."""
    s = settings or get_settings()
    if not s.database_url:
        raise RuntimeError(
            "DATABASE_URL is missing. Add Railway Postgres and set DATABASE_URL "
            "(or a local postgres:// URL)."
        )
    return psycopg.connect(s.database_url, row_factory=dict_row)


@contextmanager
def db_connection(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    conn = open_connection(settings)
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


def _jsonb(payload: dict[str, Any] | None) -> Jsonb | None:
    if payload is None:
        return None
    return Jsonb(payload)


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
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO webhook_events (
                event_message_id, event_type, event_version, subscription_id,
                channel_slug, processed_ok, error_message
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (event_message_id) DO NOTHING
            RETURNING event_message_id
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
        return cur.fetchone() is not None


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
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO channel_users (
                channel_slug, kick_user_id, username, profile_picture, is_verified,
                first_seen_at, last_seen_at, message_count
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, 1
            )
            ON CONFLICT (channel_slug, kick_user_id) DO UPDATE SET
                username = EXCLUDED.username,
                profile_picture = COALESCE(
                    EXCLUDED.profile_picture, channel_users.profile_picture
                ),
                is_verified = EXCLUDED.is_verified,
                last_seen_at = GREATEST(channel_users.last_seen_at, EXCLUDED.last_seen_at),
                message_count = channel_users.message_count + 1
            """,
            (
                channel_slug,
                kick_user_id,
                username,
                profile_picture,
                is_verified,
                seen_at,
                seen_at,
            ),
        )


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
        raise ValueError("channel_slug is required for channel_users upsert")
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
    settings = get_settings()
    payload = raw_payload if settings.store_raw_payload else None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chat_messages (
                message_id, event_message_id, channel_slug, broadcaster_user_id,
                kick_user_id, username, content, created_at, source, is_command,
                raw_payload
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (message_id) DO NOTHING
            RETURNING message_id
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
                _jsonb(payload),
            ),
        )
        return cur.fetchone() is not None


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

    settings = get_settings()
    raw = _jsonb(payload) if settings.store_raw_payload else None
    with conn.cursor() as cur:
        if is_live:
            cur.execute(
                """
                INSERT INTO stream_sessions (
                    session_id, channel_slug, broadcaster_user_id, title,
                    started_at, ended_at, is_live, raw_payload
                ) VALUES (
                    %s, %s, %s, %s, %s, NULL, TRUE, %s
                )
                ON CONFLICT (session_id) DO UPDATE SET
                    title = COALESCE(EXCLUDED.title, stream_sessions.title),
                    is_live = TRUE,
                    ended_at = NULL,
                    raw_payload = EXCLUDED.raw_payload
                """,
                (
                    session_id,
                    slug,
                    int(bc_id) if bc_id is not None else None,
                    title,
                    started_at,
                    raw,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO stream_sessions (
                    session_id, channel_slug, broadcaster_user_id, title,
                    started_at, ended_at, is_live, raw_payload
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, FALSE, %s
                )
                ON CONFLICT (session_id) DO UPDATE SET
                    is_live = FALSE,
                    ended_at = COALESCE(EXCLUDED.ended_at, NOW()),
                    title = COALESCE(EXCLUDED.title, stream_sessions.title),
                    raw_payload = EXCLUDED.raw_payload
                """,
                (
                    session_id,
                    slug,
                    int(bc_id) if bc_id is not None else None,
                    title,
                    started_at,
                    ended_at,
                    raw,
                ),
            )
    return session_id


def prune_old_webhook_events(conn: Any, *, retention_days: int | None = None) -> int:
    """Delete webhook_events older than retention; returns rows deleted."""
    days = (
        retention_days
        if retention_days is not None
        else get_settings().webhook_events_retention_days
    )
    if days <= 0:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM webhook_events
            WHERE received_at < NOW() - (%s * INTERVAL '1 day')
            """,
            (days,),
        )
        return int(cur.rowcount or 0)


def database_size_bytes(conn: Any) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_database_size(current_database()) AS bytes")
        row = cur.fetchone()
        return int(row["bytes"] if isinstance(row, dict) else row[0])


def query_leaderboard(
    conn: Any,
    *,
    channel_slug: str,
    days: int | None = 30,
    limit: int = 50,
    exclude_commands: bool = True,
) -> list[dict[str, Any]]:
    where = ["channel_slug = %s"]
    params: list[Any] = [channel_slug]
    if exclude_commands:
        where.append("NOT COALESCE(is_command, FALSE)")
    if days is not None:
        where.append("created_at >= NOW() - (%s * INTERVAL '1 day')")
        params.append(days)
    where_sql = "WHERE " + " AND ".join(where)
    params.append(limit)
    sql = f"""
        SELECT
            channel_slug,
            kick_user_id,
            MAX(username) AS username,
            COUNT(*) AS message_count,
            COUNT(DISTINCT (DATE_TRUNC('day', created_at))::DATE) AS active_days,
            MIN(created_at) AS first_message_at,
            MAX(created_at) AS last_message_at
        FROM chat_messages
        {where_sql}
        GROUP BY channel_slug, kick_user_id
        ORDER BY message_count DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def query_user_messages(
    conn: Any,
    *,
    kick_user_id: int,
    channel_slug: str | None = None,
    days: int | None = 30,
    limit: int = 200,
) -> list[dict[str, Any]]:
    params: list[Any] = [kick_user_id]
    extras = ["kick_user_id = %s"]
    if channel_slug:
        extras.append("channel_slug = %s")
        params.append(channel_slug)
    if days is not None:
        extras.append("created_at >= NOW() - (%s * INTERVAL '1 day')")
        params.append(days)
    params.append(limit)
    where_sql = " AND ".join(extras)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT message_id, channel_slug, username, content, created_at, source, is_command
            FROM chat_messages
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            params,
        )
        return list(cur.fetchall())


def query_user_cross_channel(
    conn: Any,
    *,
    kick_user_id: int | None = None,
    username: str | None = None,
    days: int | None = 30,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Operator view: one Kick user's activity broken down by channel."""
    where = ["NOT COALESCE(is_command, FALSE)"]
    params: list[Any] = []
    if kick_user_id is not None:
        where.append("kick_user_id = %s")
        params.append(kick_user_id)
    if username:
        where.append("LOWER(username) = LOWER(%s)")
        params.append(username)
    if days is not None:
        where.append("created_at >= NOW() - (%s * INTERVAL '1 day')")
        params.append(days)
    if kick_user_id is None and not username:
        raise ValueError("Provide kick_user_id or username")
    params.append(limit)
    where_sql = " AND ".join(where)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                kick_user_id,
                MAX(username) AS username,
                channel_slug,
                COUNT(*) AS message_count,
                COUNT(DISTINCT (DATE_TRUNC('day', created_at))::DATE) AS active_days,
                MIN(created_at) AS first_message_at,
                MAX(created_at) AS last_message_at
            FROM chat_messages
            WHERE {where_sql}
            GROUP BY kick_user_id, channel_slug
            ORDER BY message_count DESC
            LIMIT %s
            """,
            params,
        )
        return list(cur.fetchall())

"""Channel registry lookups against Snowflake CHANNELS table."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChannelRecord:
    channel_slug: str
    tenant_id: str
    broadcaster_user_id: int | None
    display_name: str | None
    status: str


def extract_payload_channel_hints(
    payload: dict[str, Any],
) -> tuple[str | None, int | None]:
    """Read broadcaster slug / id from a Kick event payload."""
    broadcaster = payload.get("broadcaster") or {}
    slug = broadcaster.get("channel_slug")
    bc_id = broadcaster.get("user_id")
    return (
        str(slug) if slug else None,
        int(bc_id) if bc_id is not None else None,
    )


def list_active_channels(conn: Any) -> list[ChannelRecord]:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT CHANNEL_SLUG, TENANT_ID, BROADCASTER_USER_ID, DISPLAY_NAME, STATUS
            FROM CHANNELS
            WHERE LOWER(STATUS) = 'active'
            ORDER BY CHANNEL_SLUG
            """
        )
        rows = cur.fetchall()
        return [
            ChannelRecord(
                channel_slug=str(r[0]),
                tenant_id=str(r[1] or "default"),
                broadcaster_user_id=int(r[2]) if r[2] is not None else None,
                display_name=str(r[3]) if r[3] is not None else None,
                status=str(r[4] or "active"),
            )
            for r in rows
        ]
    finally:
        cur.close()


def get_channel_by_slug(conn: Any, channel_slug: str) -> ChannelRecord | None:
    slug = channel_slug.strip().lower()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT CHANNEL_SLUG, TENANT_ID, BROADCASTER_USER_ID, DISPLAY_NAME, STATUS
            FROM CHANNELS
            WHERE LOWER(CHANNEL_SLUG) = %s
            """,
            (slug,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return ChannelRecord(
            channel_slug=str(row[0]),
            tenant_id=str(row[1] or "default"),
            broadcaster_user_id=int(row[2]) if row[2] is not None else None,
            display_name=str(row[3]) if row[3] is not None else None,
            status=str(row[4] or "active"),
        )
    finally:
        cur.close()


def get_channel_by_broadcaster_id(conn: Any, broadcaster_user_id: int) -> ChannelRecord | None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT CHANNEL_SLUG, TENANT_ID, BROADCASTER_USER_ID, DISPLAY_NAME, STATUS
            FROM CHANNELS
            WHERE BROADCASTER_USER_ID = %s
            """,
            (broadcaster_user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return ChannelRecord(
            channel_slug=str(row[0]),
            tenant_id=str(row[1] or "default"),
            broadcaster_user_id=int(row[2]) if row[2] is not None else None,
            display_name=str(row[3]) if row[3] is not None else None,
            status=str(row[4] or "active"),
        )
    finally:
        cur.close()


def resolve_registered_channel(
    conn: Any,
    *,
    channel_slug: str | None,
    broadcaster_user_id: int | None,
) -> ChannelRecord | None:
    """Resolve payload channel against CHANNELS; prefer slug, then broadcaster id."""
    if channel_slug:
        found = get_channel_by_slug(conn, channel_slug)
        if found and found.status.lower() == "active":
            return found
        if found:
            logger.warning("Channel %s exists but status=%s", found.channel_slug, found.status)
            return None
    if broadcaster_user_id is not None:
        found = get_channel_by_broadcaster_id(conn, broadcaster_user_id)
        if found and found.status.lower() == "active":
            return found
    return None


def upsert_channel(
    conn: Any,
    *,
    channel_slug: str,
    broadcaster_user_id: int | None,
    display_name: str | None = None,
    tenant_id: str = "default",
    chat_subscription_id: str | None = None,
    livestream_subscription_id: str | None = None,
    status: str = "active",
) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            MERGE INTO CHANNELS t
            USING (
                SELECT
                    %s AS CHANNEL_SLUG,
                    %s AS TENANT_ID,
                    %s AS BROADCASTER_USER_ID,
                    %s AS DISPLAY_NAME,
                    %s AS STATUS,
                    %s AS CHAT_SUBSCRIPTION_ID,
                    %s AS LIVESTREAM_SUBSCRIPTION_ID
            ) s
            ON LOWER(t.CHANNEL_SLUG) = LOWER(s.CHANNEL_SLUG)
            WHEN MATCHED THEN UPDATE SET
                TENANT_ID = s.TENANT_ID,
                BROADCASTER_USER_ID = COALESCE(s.BROADCASTER_USER_ID, t.BROADCASTER_USER_ID),
                DISPLAY_NAME = COALESCE(s.DISPLAY_NAME, t.DISPLAY_NAME),
                STATUS = s.STATUS,
                CHAT_SUBSCRIPTION_ID = COALESCE(s.CHAT_SUBSCRIPTION_ID, t.CHAT_SUBSCRIPTION_ID),
                LIVESTREAM_SUBSCRIPTION_ID = COALESCE(
                    s.LIVESTREAM_SUBSCRIPTION_ID, t.LIVESTREAM_SUBSCRIPTION_ID
                ),
                UPDATED_AT = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT (
                CHANNEL_SLUG, TENANT_ID, BROADCASTER_USER_ID, DISPLAY_NAME, STATUS,
                CHAT_SUBSCRIPTION_ID, LIVESTREAM_SUBSCRIPTION_ID
            ) VALUES (
                s.CHANNEL_SLUG, s.TENANT_ID, s.BROADCASTER_USER_ID, s.DISPLAY_NAME, s.STATUS,
                s.CHAT_SUBSCRIPTION_ID, s.LIVESTREAM_SUBSCRIPTION_ID
            )
            """,
            (
                channel_slug.strip().lower(),
                tenant_id,
                broadcaster_user_id,
                display_name,
                status,
                chat_subscription_id,
                livestream_subscription_id,
            ),
        )
    finally:
        cur.close()

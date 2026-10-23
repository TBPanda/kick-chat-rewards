"""Channel registry lookups against Postgres channels table."""

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


def _row_to_channel(row: dict[str, Any] | tuple[Any, ...]) -> ChannelRecord:
    if isinstance(row, dict):
        return ChannelRecord(
            channel_slug=str(row["channel_slug"]),
            tenant_id=str(row.get("tenant_id") or "default"),
            broadcaster_user_id=(
                int(row["broadcaster_user_id"])
                if row.get("broadcaster_user_id") is not None
                else None
            ),
            display_name=str(row["display_name"]) if row.get("display_name") else None,
            status=str(row.get("status") or "active"),
        )
    return ChannelRecord(
        channel_slug=str(row[0]),
        tenant_id=str(row[1] or "default"),
        broadcaster_user_id=int(row[2]) if row[2] is not None else None,
        display_name=str(row[3]) if row[3] is not None else None,
        status=str(row[4] or "active"),
    )


def list_active_channels(conn: Any) -> list[ChannelRecord]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT channel_slug, tenant_id, broadcaster_user_id, display_name, status
            FROM channels
            WHERE LOWER(status) = 'active'
            ORDER BY channel_slug
            """
        )
        return [_row_to_channel(r) for r in cur.fetchall()]


def get_channel_by_slug(conn: Any, channel_slug: str) -> ChannelRecord | None:
    slug = channel_slug.strip().lower()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT channel_slug, tenant_id, broadcaster_user_id, display_name, status
            FROM channels
            WHERE LOWER(channel_slug) = %s
            """,
            (slug,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return _row_to_channel(row)


def get_channel_by_broadcaster_id(conn: Any, broadcaster_user_id: int) -> ChannelRecord | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT channel_slug, tenant_id, broadcaster_user_id, display_name, status
            FROM channels
            WHERE broadcaster_user_id = %s
            """,
            (broadcaster_user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return _row_to_channel(row)


def resolve_registered_channel(
    conn: Any,
    *,
    channel_slug: str | None,
    broadcaster_user_id: int | None,
) -> ChannelRecord | None:
    """Resolve payload channel against channels; prefer slug, then broadcaster id."""
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
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO channels (
                channel_slug, tenant_id, broadcaster_user_id, display_name, status,
                chat_subscription_id, livestream_subscription_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (channel_slug) DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                broadcaster_user_id = COALESCE(
                    EXCLUDED.broadcaster_user_id, channels.broadcaster_user_id
                ),
                display_name = COALESCE(EXCLUDED.display_name, channels.display_name),
                status = EXCLUDED.status,
                chat_subscription_id = COALESCE(
                    EXCLUDED.chat_subscription_id, channels.chat_subscription_id
                ),
                livestream_subscription_id = COALESCE(
                    EXCLUDED.livestream_subscription_id,
                    channels.livestream_subscription_id
                ),
                updated_at = NOW()
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

"""Periodically ensure Kick chat/livestream webhook subscriptions stay active."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from ingest.channels import list_active_channels, upsert_channel
from ingest.config import Settings, get_settings
from ingest.kick_api import (
    REQUIRED_EVENTS,
    extract_subscription_ids,
    get_app_access_token,
    list_subscriptions,
    subscribe,
    subscriptions_by_broadcaster,
)
from ingest.snowflake_writer import snowflake_connection

logger = logging.getLogger(__name__)


class SubscriptionWatchdog:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        interval_sec: float = 120.0,
    ) -> None:
        self._settings = settings or get_settings()
        self._interval_sec = max(30.0, interval_sec)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_check_at: str | None = None
        self._last_ok: bool | None = None
        self._last_error: str | None = None
        self._repairs = 0

    @property
    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": bool(self._thread and self._thread.is_alive()),
                "interval_sec": self._interval_sec,
                "last_check_at": self._last_check_at,
                "last_ok": self._last_ok,
                "last_error": self._last_error,
                "repairs": self._repairs,
            }

    def start(self) -> None:
        if not self._settings.kick_client_id or not self._settings.kick_client_secret:
            logger.warning("Subscription watchdog disabled — missing Kick credentials")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="kick-subscription-watchdog",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Subscription watchdog started (interval=%ss)",
            int(self._interval_sec),
        )

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("Subscription watchdog stopped")

    def _run(self) -> None:
        # Immediate check on boot (covers deploy gaps).
        self.check_once()
        while not self._stop.wait(self._interval_sec):
            self.check_once()

    def check_once(self) -> None:
        try:
            repaired = self._ensure_subscriptions()
            with self._lock:
                self._last_check_at = datetime.now(timezone.utc).isoformat()
                self._last_ok = True
                self._last_error = None
                self._repairs += repaired
            if repaired:
                logger.warning(
                    "Subscription watchdog repaired %s channel subscription set(s)",
                    repaired,
                )
            else:
                logger.info("Subscription watchdog OK — required events present")
        except Exception as exc:
            with self._lock:
                self._last_check_at = datetime.now(timezone.utc).isoformat()
                self._last_ok = False
                self._last_error = str(exc)
            logger.exception("Subscription watchdog check failed")

    def _ensure_subscriptions(self) -> int:
        settings = self._settings
        token = get_app_access_token(settings.kick_client_id, settings.kick_client_secret)
        current = subscriptions_by_broadcaster(list_subscriptions(token))
        required = {e["name"].lower() for e in REQUIRED_EVENTS}

        targets: list[tuple[str, int]] = []
        with snowflake_connection(settings) as conn:
            for ch in list_active_channels(conn):
                if ch.broadcaster_user_id is not None:
                    targets.append((ch.channel_slug, ch.broadcaster_user_id))

        # Always include env bootstrap channel even if CHANNELS is empty/stale.
        bootstrap_slug = settings.kick_channel_slug.strip().lower()
        bootstrap_id = settings.kick_broadcaster_user_id
        if (
            bootstrap_slug
            and bootstrap_id
            and not any(b == bootstrap_id for _, b in targets)
        ):
            targets.append((bootstrap_slug, bootstrap_id))

        repaired = 0
        for slug, broadcaster_id in targets:
            have = current.get(broadcaster_id, set())
            missing = required - have
            if not missing:
                continue
            logger.warning(
                "Missing Kick events for slug=%s broadcaster=%s: %s — re-subscribing",
                slug,
                broadcaster_id,
                sorted(missing),
            )
            result = subscribe(token, broadcaster_id)
            chat_sub, live_sub = extract_subscription_ids(result)
            with snowflake_connection(settings) as conn:
                upsert_channel(
                    conn,
                    channel_slug=slug,
                    broadcaster_user_id=broadcaster_id,
                    display_name=slug,
                    chat_subscription_id=chat_sub,
                    livestream_subscription_id=live_sub,
                    status="active",
                )
                conn.commit()
            # Refresh local view so we don't double-subscribe in same pass.
            current[broadcaster_id] = current.get(broadcaster_id, set()) | required
            repaired += 1
        return repaired


_watchdog: SubscriptionWatchdog | None = None


def get_subscription_watchdog() -> SubscriptionWatchdog:
    global _watchdog
    if _watchdog is None:
        settings = get_settings()
        _watchdog = SubscriptionWatchdog(
            settings,
            interval_sec=settings.subscription_watchdog_interval_sec,
        )
    return _watchdog

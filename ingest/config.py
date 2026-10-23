"""Shared configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root if present
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    # Kick
    kick_client_id: str
    kick_client_secret: str
    kick_broadcaster_user_id: int
    kick_channel_slug: str
    kick_webhook_skip_verify: bool

    # Postgres (Railway Postgres plugin sets DATABASE_URL)
    database_url: str

    # App
    report_password: str
    host: str
    port: int
    # Re-subscribe missing Kick events (seconds; min 30 enforced in watchdog)
    subscription_watchdog_interval_sec: float
    subscription_watchdog_enabled: bool
    # Storage guards (Railway ~5GB): skip bulky JSON; prune webhook log
    store_raw_payload: bool
    webhook_events_retention_days: int


def _env(name: str, default: str = "") -> str:
    """Read env var and strip surrounding whitespace (common Railway/.env paste issue)."""
    return (os.getenv(name, default) or default).strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        kick_client_id=_env("KICK_CLIENT_ID"),
        kick_client_secret=_env("KICK_CLIENT_SECRET"),
        kick_broadcaster_user_id=int(_env("KICK_BROADCASTER_USER_ID", "538671")),
        kick_channel_slug=_env("KICK_CHANNEL_SLUG", "amirphanthom"),
        kick_webhook_skip_verify=_env("KICK_WEBHOOK_SKIP_VERIFY", "false").lower()
        in ("1", "true", "yes"),
        database_url=_env("DATABASE_URL"),
        report_password=_env("REPORT_PASSWORD", "changeme"),
        host=_env("HOST", "0.0.0.0"),
        port=int(_env("PORT", "8000")),
        subscription_watchdog_interval_sec=float(
            _env("SUBSCRIPTION_WATCHDOG_INTERVAL_SEC", "120")
        ),
        subscription_watchdog_enabled=_env(
            "SUBSCRIPTION_WATCHDOG_ENABLED", "true"
        ).lower()
        in ("1", "true", "yes"),
        # Default off — raw Kick JSON dominates disk under a 5GB plan
        store_raw_payload=_env("STORE_RAW_PAYLOAD", "false").lower()
        in ("1", "true", "yes"),
        webhook_events_retention_days=int(
            _env("WEBHOOK_EVENTS_RETENTION_DAYS", "7")
        ),
    )

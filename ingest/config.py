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

    # Snowflake
    snowflake_account: str
    snowflake_user: str
    snowflake_password: str
    snowflake_warehouse: str
    snowflake_database: str
    snowflake_schema: str
    snowflake_role: str

    # App
    report_password: str
    host: str
    port: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        kick_client_id=os.getenv("KICK_CLIENT_ID", ""),
        kick_client_secret=os.getenv("KICK_CLIENT_SECRET", ""),
        kick_broadcaster_user_id=int(os.getenv("KICK_BROADCASTER_USER_ID", "538671")),
        kick_channel_slug=os.getenv("KICK_CHANNEL_SLUG", "amirphanthom"),
        kick_webhook_skip_verify=os.getenv("KICK_WEBHOOK_SKIP_VERIFY", "false").lower()
        in ("1", "true", "yes"),
        snowflake_account=os.getenv("SNOWFLAKE_ACCOUNT", ""),
        snowflake_user=os.getenv("SNOWFLAKE_USER", ""),
        snowflake_password=os.getenv("SNOWFLAKE_PASSWORD", ""),
        snowflake_warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        snowflake_database=os.getenv("SNOWFLAKE_DATABASE", "KICK_CHAT"),
        snowflake_schema=os.getenv("SNOWFLAKE_SCHEMA", "AMIRPHANTHOM"),
        snowflake_role=os.getenv("SNOWFLAKE_ROLE", "SYSADMIN"),
        report_password=os.getenv("REPORT_PASSWORD", "changeme"),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )

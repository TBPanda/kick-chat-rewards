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
    # Preferred for Railway: RSA key-pair (avoids MFA on human users)
    snowflake_private_key: str
    snowflake_private_key_passphrase: str
    snowflake_warehouse: str
    snowflake_database: str
    snowflake_schema: str
    snowflake_role: str

    # App
    report_password: str
    host: str
    port: int


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
        snowflake_account=_env("SNOWFLAKE_ACCOUNT"),
        snowflake_user=_env("SNOWFLAKE_USER"),
        snowflake_password=_env("SNOWFLAKE_PASSWORD"),
        snowflake_private_key=_env("SNOWFLAKE_PRIVATE_KEY"),
        snowflake_private_key_passphrase=_env("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"),
        snowflake_warehouse=_env("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        snowflake_database=_env("SNOWFLAKE_DATABASE", "KICK_CHAT"),
        snowflake_schema=_env("SNOWFLAKE_SCHEMA", "AMIRPHANTHOM"),
        snowflake_role=_env("SNOWFLAKE_ROLE", "SYSADMIN"),
        report_password=_env("REPORT_PASSWORD", "changeme"),
        host=_env("HOST", "0.0.0.0"),
        port=int(_env("PORT", "8000")),
    )

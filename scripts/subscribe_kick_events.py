#!/usr/bin/env python3
"""Subscribe Kick app to one or more channel chat + livestream webhooks.

Requires:
  - Kick Developer app with webhooks enabled and a public webhook URL set
  - KICK_CLIENT_ID / KICK_CLIENT_SECRET in .env
  - Snowflake CHANNELS registry (sql/001_ddl.sql applied; SNOWFLAKE_SCHEMA=CORE)

Usage:
  python scripts/subscribe_kick_events.py
  python scripts/subscribe_kick_events.py --slug amirphanthom
  python scripts/subscribe_kick_events.py --slugs amirphanthom,otherstreamer
  python scripts/subscribe_kick_events.py --list
  python scripts/subscribe_kick_events.py --resolve-slug amirphanthom
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.channels import upsert_channel  # noqa: E402
from ingest.config import get_settings  # noqa: E402
from ingest.kick_api import (  # noqa: E402
    REQUIRED_EVENTS,
    extract_broadcaster_id,
    extract_subscription_ids,
    get_app_access_token,
    list_subscriptions,
    resolve_channel,
    subscribe,
)
from ingest.snowflake_writer import snowflake_connection  # noqa: E402


def subscribe_and_register(token: str, slug: str) -> None:
    settings = get_settings()
    resolved = resolve_channel(slug, token)
    broadcaster_id = extract_broadcaster_id(resolved)
    if broadcaster_id is None:
        raise RuntimeError(f"Could not resolve broadcaster id for slug={slug}: {resolved}")

    print(f"Subscribing slug={slug} broadcaster_user_id={broadcaster_id}")
    for ev in REQUIRED_EVENTS:
        print(f"  - {ev['name']} v{ev['version']}")

    result = subscribe(token, broadcaster_id)
    print(json.dumps(result, indent=2))
    chat_sub, live_sub = extract_subscription_ids(result)

    with snowflake_connection(settings) as conn:
        upsert_channel(
            conn,
            channel_slug=slug,
            broadcaster_user_id=broadcaster_id,
            display_name=slug,
            tenant_id="default",
            chat_subscription_id=chat_sub,
            livestream_subscription_id=live_sub,
            status="active",
        )
        conn.commit()
    print(f"Registered channel '{slug}' in Snowflake CHANNELS.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Kick event subscriptions")
    parser.add_argument("--list", action="store_true", help="List current subscriptions")
    parser.add_argument(
        "--resolve-slug",
        metavar="SLUG",
        help="Resolve channel slug to broadcaster user id via Kick API",
    )
    parser.add_argument(
        "--slug",
        metavar="SLUG",
        help="Subscribe + register a single channel slug",
    )
    parser.add_argument(
        "--slugs",
        metavar="SLUG,SLUG",
        help="Comma-separated channel slugs to subscribe + register",
    )
    parser.add_argument(
        "--broadcaster-user-id",
        type=int,
        default=None,
        help="Override broadcaster id (single-channel legacy mode; use with --slug)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.kick_client_id or not settings.kick_client_secret:
        print(
            "Set KICK_CLIENT_ID and KICK_CLIENT_SECRET in .env "
            "(from https://kick.com/settings/developer)",
            file=sys.stderr,
        )
        return 1

    token = get_app_access_token(settings.kick_client_id, settings.kick_client_secret)
    print("Obtained app access token.")

    if args.resolve_slug:
        data = resolve_channel(args.resolve_slug, token)
        print(json.dumps(data, indent=2))
        return 0

    if args.list:
        data = list_subscriptions(token)
        print(json.dumps(data, indent=2))
        return 0

    slugs: list[str] = []
    if args.slugs:
        slugs.extend(s.strip() for s in args.slugs.split(",") if s.strip())
    if args.slug:
        slugs.append(args.slug.strip())
    if not slugs:
        slugs.append(settings.kick_channel_slug)

    seen: set[str] = set()
    ordered: list[str] = []
    for s in slugs:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(s)

    for slug in ordered:
        if args.broadcaster_user_id is not None and len(ordered) == 1:
            result = subscribe(token, args.broadcaster_user_id)
            print(json.dumps(result, indent=2))
            chat_sub, live_sub = extract_subscription_ids(result)
            with snowflake_connection(settings) as conn:
                upsert_channel(
                    conn,
                    channel_slug=slug,
                    broadcaster_user_id=args.broadcaster_user_id,
                    display_name=slug,
                    chat_subscription_id=chat_sub,
                    livestream_subscription_id=live_sub,
                )
                conn.commit()
            print(f"Registered channel '{slug}' in Snowflake CHANNELS.")
        else:
            subscribe_and_register(token, slug)

    print(
        "\nEnsure your Kick app webhook URL points at "
        "https://<your-host>/webhooks/kick and webhooks are enabled."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

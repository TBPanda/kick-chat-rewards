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

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.channels import upsert_channel  # noqa: E402
from ingest.config import get_settings  # noqa: E402
from ingest.snowflake_writer import snowflake_connection  # noqa: E402

TOKEN_URL = "https://id.kick.com/oauth/token"
API_BASE = "https://api.kick.com/public/v1"

EVENTS = [
    {"name": "chat.message.sent", "version": 1},
    {"name": "livestream.status.updated", "version": 1},
]


def get_app_access_token(client_id: str, client_secret: str) -> str:
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"No access_token in response: {data}")
        return token


def resolve_channel(slug: str, token: str) -> dict:
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            f"{API_BASE}/channels",
            params={"slug": slug},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


def list_subscriptions(token: str) -> dict:
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            f"{API_BASE}/events/subscriptions",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


def subscribe(token: str, broadcaster_user_id: int) -> dict:
    body = {
        "broadcaster_user_id": broadcaster_user_id,
        "events": EVENTS,
        "method": "webhook",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{API_BASE}/events/subscriptions",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=body,
        )
        if resp.status_code >= 400:
            print(f"Error {resp.status_code}: {resp.text}", file=sys.stderr)
            resp.raise_for_status()
        return resp.json()


def _extract_broadcaster_id(resolve_payload: dict) -> int | None:
    data = resolve_payload.get("data")
    if isinstance(data, list) and data:
        row = data[0]
        for key in ("broadcaster_user_id", "user_id", "id"):
            if key in row and row[key] is not None:
                return int(row[key])
        user = row.get("user") or {}
        if user.get("id") is not None:
            return int(user["id"])
    return None


def _extract_subscription_ids(result: dict) -> tuple[str | None, str | None]:
    """Best-effort parse of Kick subscribe response for chat / livestream ids."""
    chat_id = None
    live_id = None
    data = result.get("data")
    rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("id") or row.get("subscription_id")
        ev = (row.get("event") or row.get("name") or "")
        if isinstance(ev, dict):
            ev = ev.get("name") or ""
        ev_l = str(ev).lower()
        if sid and "chat" in ev_l:
            chat_id = str(sid)
        elif sid and "livestream" in ev_l:
            live_id = str(sid)
        elif sid and chat_id is None:
            chat_id = str(sid)
    return chat_id, live_id


def subscribe_and_register(token: str, slug: str) -> None:
    settings = get_settings()
    resolved = resolve_channel(slug, token)
    broadcaster_id = _extract_broadcaster_id(resolved)
    if broadcaster_id is None:
        raise RuntimeError(f"Could not resolve broadcaster id for slug={slug}: {resolved}")

    print(f"Subscribing slug={slug} broadcaster_user_id={broadcaster_id}")
    for ev in EVENTS:
        print(f"  - {ev['name']} v{ev['version']}")

    result = subscribe(token, broadcaster_id)
    print(json.dumps(result, indent=2))
    chat_sub, live_sub = _extract_subscription_ids(result)

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

    # Deduplicate while preserving order
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
            chat_sub, live_sub = _extract_subscription_ids(result)
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

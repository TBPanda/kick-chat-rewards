#!/usr/bin/env python3
"""Subscribe Kick app to amirphanthom chat + livestream webhooks.

Requires:
  - Kick Developer app with webhooks enabled and a public webhook URL set
  - KICK_CLIENT_ID / KICK_CLIENT_SECRET in .env
  - KICK_BROADCASTER_USER_ID (default 538671 for amirphanthom)

Usage:
  python scripts/subscribe_kick_events.py
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

from ingest.config import get_settings  # noqa: E402

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Kick event subscriptions")
    parser.add_argument("--list", action="store_true", help="List current subscriptions")
    parser.add_argument(
        "--resolve-slug",
        metavar="SLUG",
        help="Resolve channel slug to broadcaster user id via Kick API",
    )
    parser.add_argument(
        "--broadcaster-user-id",
        type=int,
        default=None,
        help="Override KICK_BROADCASTER_USER_ID",
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

    broadcaster_id = args.broadcaster_user_id or settings.kick_broadcaster_user_id
    print(f"Subscribing broadcaster_user_id={broadcaster_id} to:")
    for ev in EVENTS:
        print(f"  - {ev['name']} v{ev['version']}")

    result = subscribe(token, broadcaster_id)
    print(json.dumps(result, indent=2))
    print(
        "\nEnsure your Kick app webhook URL points at "
        "https://<your-host>/webhooks/kick and webhooks are enabled."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

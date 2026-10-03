"""Kick Events API helpers (token, list/subscribe, channel resolve)."""

from __future__ import annotations

from typing import Any

import httpx

TOKEN_URL = "https://id.kick.com/oauth/token"
API_BASE = "https://api.kick.com/public/v1"

REQUIRED_EVENTS = [
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
        return str(token)


def resolve_channel(slug: str, token: str) -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            f"{API_BASE}/channels",
            params={"slug": slug},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


def list_subscriptions(token: str) -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            f"{API_BASE}/events/subscriptions",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


def subscribe(token: str, broadcaster_user_id: int) -> dict[str, Any]:
    body = {
        "broadcaster_user_id": broadcaster_user_id,
        "events": REQUIRED_EVENTS,
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
        resp.raise_for_status()
        return resp.json()


def extract_broadcaster_id(resolve_payload: dict[str, Any]) -> int | None:
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


def extract_subscription_ids(result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Best-effort parse of Kick subscribe response for chat / livestream ids."""
    chat_id = None
    live_id = None
    data = result.get("data")
    rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("id") or row.get("subscription_id")
        ev = row.get("event") or row.get("name") or ""
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


def subscriptions_by_broadcaster(
    list_payload: dict[str, Any],
) -> dict[int, set[str]]:
    """Map broadcaster_user_id -> set of event names currently subscribed."""
    out: dict[int, set[str]] = {}
    data = list_payload.get("data")
    rows = data if isinstance(data, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        bc = row.get("broadcaster_user_id")
        ev = row.get("event") or ""
        if bc is None or not ev:
            continue
        out.setdefault(int(bc), set()).add(str(ev).lower())
    return out

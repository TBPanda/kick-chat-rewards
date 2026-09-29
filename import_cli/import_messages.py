#!/usr/bin/env python3
"""Import historical chat messages from CSV or JSON into Snowflake.

Does NOT scrape StreamerStats (prohibited by their ToS). Use only for
lawful manual exports or other permitted dumps.

CSV columns (header required; extras ignored):
  message_id, kick_user_id, username, content, created_at
Optional: channel_slug

JSON: array of objects with the same fields, or Kick-like
{message_id, content, created_at, sender: {user_id, username}} shape.

Usage:
  python -m import_cli.import_messages path/to/export.csv
  python -m import_cli.import_messages path/to/export.json --dry-run
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import click

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.config import get_settings  # noqa: E402
from ingest.snowflake_writer import (  # noqa: E402
    _parse_ts,
    insert_chat_message,
    should_skip_chat_message,
    snowflake_connection,
    upsert_channel_user,
)


def _normalize_row(raw: dict[str, Any], default_slug: str) -> dict[str, Any] | None:
    """Normalize CSV/JSON row or Kick-shaped object into insert fields."""
    if "sender" in raw and isinstance(raw["sender"], dict):
        sender = raw["sender"]
        message_id = str(raw.get("message_id") or uuid4())
        kick_user_id = sender.get("user_id")
        username = sender.get("username") or "unknown"
        content = raw.get("content")
        created_at = raw.get("created_at")
        channel_slug = (raw.get("broadcaster") or {}).get("channel_slug") or default_slug
        if kick_user_id is None:
            return None
        return {
            "message_id": message_id,
            "kick_user_id": int(kick_user_id),
            "username": str(username),
            "content": content,
            "created_at": created_at,
            "channel_slug": channel_slug,
            "raw": raw,
        }

    keys = {k.lower().strip(): v for k, v in raw.items()}
    kick_user_id = keys.get("kick_user_id") or keys.get("user_id")
    username = keys.get("username") or keys.get("user") or "unknown"
    content = keys.get("content") or keys.get("message") or keys.get("text")
    created_at = keys.get("created_at") or keys.get("timestamp") or keys.get("time")
    message_id = keys.get("message_id") or keys.get("id")
    channel_slug = keys.get("channel_slug") or default_slug

    if kick_user_id is None or created_at is None:
        return None
    if not message_id:
        message_id = (
            f"import:{kick_user_id}:{created_at}:{hash(str(content)) & 0xFFFFFFFF:x}"
        )

    return {
        "message_id": str(message_id),
        "kick_user_id": int(kick_user_id),
        "username": str(username),
        "content": content,
        "created_at": created_at,
        "channel_slug": str(channel_slug),
        "raw": raw,
    }


def iter_rows(path: Path) -> Iterator[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                yield dict(row)
        return
    if suffix == ".jsonl":
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
        return
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "messages" in data:
            data = data["messages"]
        if not isinstance(data, list):
            raise click.ClickException("JSON must be an array (or {messages: [...]})")
        for item in data:
            if isinstance(item, dict):
                yield item
        return
    raise click.ClickException("Supported formats: .csv, .json, .jsonl")


@click.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, help="Parse and count only; no Snowflake writes")
@click.option("--limit", type=int, default=None, help="Max rows to import")
def main(path: Path, dry_run: bool, limit: int | None) -> None:
    """Import historical chat from CSV or JSON into CHAT_MESSAGES."""
    settings = get_settings()

    normalized: list[dict[str, Any]] = []
    skipped = 0
    for i, raw in enumerate(iter_rows(path)):
        if limit is not None and i >= limit:
            break
        row = _normalize_row(raw, settings.kick_channel_slug)
        if row is None:
            skipped += 1
            continue
        if should_skip_chat_message(row["username"], row.get("content")):
            skipped += 1
            continue
        normalized.append(row)

    click.echo(f"Parsed {len(normalized)} rows ({skipped} skipped)")
    if dry_run:
        if normalized:
            click.echo(f"Sample: {normalized[0]}")
        return

    inserted = 0
    duplicates = 0
    with snowflake_connection(settings) as conn:
        for row in normalized:
            created_at = _parse_ts(str(row["created_at"]))
            ok = insert_chat_message(
                conn,
                message_id=row["message_id"],
                event_message_id=None,
                channel_slug=row["channel_slug"],
                broadcaster_user_id=settings.kick_broadcaster_user_id,
                kick_user_id=row["kick_user_id"],
                username=row["username"],
                content=row["content"],
                created_at=created_at,
                source="import",
                raw_payload=row["raw"],
            )
            if ok:
                inserted += 1
                upsert_channel_user(
                    conn,
                    kick_user_id=row["kick_user_id"],
                    username=row["username"],
                    channel_slug=row["channel_slug"],
                    profile_picture=None,
                    is_verified=False,
                    seen_at=created_at,
                )
            else:
                duplicates += 1
        conn.commit()

    click.echo(f"Inserted {inserted}, duplicates {duplicates}")


if __name__ == "__main__":
    main()

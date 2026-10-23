#!/usr/bin/env python3
"""Reclaim Postgres space under Railway's ~5GB plan.

- Truncates webhook_events (idempotency log; safe to clear)
- Nulls chat_messages.raw_payload / stream_sessions.raw_payload (bulky JSON)
- VACUUM FULL on touched tables (requires brief exclusive lock)

Usage:
  PYTHONPATH=. python scripts/reclaim_postgres_space.py
  PYTHONPATH=. python scripts/reclaim_postgres_space.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.config import get_settings  # noqa: E402
from ingest.db import open_connection  # noqa: E402

# Soft ceiling for Railway hobby / small plans
SOFT_LIMIT_BYTES = 4 * 1024**3  # 4 GiB — leave headroom under 5GB


def _size_report(cur: object) -> tuple[int, list[tuple[str, int]]]:
    cur.execute(  # type: ignore[attr-defined]
        "SELECT pg_database_size(current_database()) AS bytes"
    )
    row = cur.fetchone()  # type: ignore[attr-defined]
    db_bytes = int(row["bytes"] if isinstance(row, dict) else row[0])
    cur.execute(  # type: ignore[attr-defined]
        """
        SELECT relname AS table_name,
               pg_total_relation_size(quote_ident(relname)::regclass) AS bytes
        FROM pg_stat_user_tables
        ORDER BY 2 DESC
        """
    )
    tables = [
        (
            str(r["table_name"] if isinstance(r, dict) else r[0]),
            int(r["bytes"] if isinstance(r, dict) else r[1]),
        )
        for r in cur.fetchall()  # type: ignore[attr-defined]
    ]
    return db_bytes, tables


def _pretty(n: int) -> str:
    for unit, div in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if n >= div:
            return f"{n / div:.2f} {unit}"
    return f"{n} B"


def main() -> int:
    parser = argparse.ArgumentParser(description="Reclaim Postgres disk under 5GB limit")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--keep-webhook-days",
        type=int,
        default=0,
        help="If >0, delete webhook_events older than N days instead of truncating",
    )
    args = parser.parse_args()

    get_settings.cache_clear()
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL missing", file=sys.stderr)
        return 1

    conn = open_connection(settings)
    try:
        # VACUUM FULL cannot run inside a transaction block
        conn.autocommit = True
        with conn.cursor() as cur:
            db_bytes, tables = _size_report(cur)
            print(f"Database size: {_pretty(db_bytes)} / soft limit {_pretty(SOFT_LIMIT_BYTES)}")
            for name, b in tables:
                print(f"  {name}: {_pretty(b)}")
            if db_bytes >= SOFT_LIMIT_BYTES:
                print("WARNING: at or above soft limit — reclaim strongly recommended")

            if args.dry_run:
                print("Dry run — no changes.")
                return 0

            if args.keep_webhook_days > 0:
                cur.execute(
                    "DELETE FROM webhook_events WHERE received_at < NOW() - (%s * INTERVAL '1 day')",
                    (args.keep_webhook_days,),
                )
                print(f"Deleted old webhook_events (>{args.keep_webhook_days}d): {cur.rowcount}")
            else:
                cur.execute("TRUNCATE webhook_events")
                print("Truncated webhook_events")

            cur.execute("UPDATE chat_messages SET raw_payload = NULL WHERE raw_payload IS NOT NULL")
            print(f"Nulled chat_messages.raw_payload: {cur.rowcount}")
            cur.execute(
                "UPDATE stream_sessions SET raw_payload = NULL WHERE raw_payload IS NOT NULL"
            )
            print(f"Nulled stream_sessions.raw_payload: {cur.rowcount}")

            for table in ("webhook_events", "chat_messages", "stream_sessions"):
                print(f"VACUUM FULL {table}...")
                cur.execute(f"VACUUM FULL {table}")

            db_bytes, tables = _size_report(cur)
            print(f"After reclaim: {_pretty(db_bytes)}")
            for name, b in tables:
                print(f"  {name}: {_pretty(b)}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

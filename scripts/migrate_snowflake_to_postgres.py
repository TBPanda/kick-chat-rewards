#!/usr/bin/env python3
"""One-shot copy: Snowflake KICK_CHAT.CORE → Postgres (DATABASE_URL).

Storage-safe defaults for Railway ~5GB plans:
  - skips webhook_events (huge, low value)
  - skips raw_payload JSON columns
  - small batches + sleep between commits
  - aborts if Postgres grows past --max-db-gb (default 4.0)

Requires (in .env):
  DATABASE_URL=...
  SNOWFLAKE_ACCOUNT / SNOWFLAKE_USER / SNOWFLAKE_PRIVATE_KEY (or PASSWORD)

Install:
  pip install -r requirements-migrate.txt

Usage:
  PYTHONPATH=. python scripts/migrate_snowflake_to_postgres.py --dry-run
  PYTHONPATH=. python scripts/migrate_snowflake_to_postgres.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from ingest.db import database_size_bytes, db_connection, open_connection  # noqa: E402

SQL_CORE = [
    ROOT / "sql" / "001_ddl.sql",
    ROOT / "sql" / "002_views.sql",
]

# Tables that are safe/needed for the pet project (no webhook_events by default)
CORE_TABLES: list[tuple[str, str, list[str]]] = [
    (
        "TENANTS",
        "tenants",
        ["tenant_id", "display_name", "status", "created_at"],
    ),
    (
        "CHANNELS",
        "channels",
        [
            "channel_slug",
            "tenant_id",
            "broadcaster_user_id",
            "display_name",
            "status",
            "chat_subscription_id",
            "livestream_subscription_id",
            "created_at",
            "updated_at",
        ],
    ),
    (
        "CHAT_MESSAGES",
        "chat_messages",
        [
            "message_id",
            "event_message_id",
            "channel_slug",
            "broadcaster_user_id",
            "kick_user_id",
            "username",
            "content",
            "created_at",
            "source",
            "is_command",
            "raw_payload",
            "ingested_at",
        ],
    ),
    (
        "CHANNEL_USERS",
        "channel_users",
        [
            "channel_slug",
            "kick_user_id",
            "username",
            "profile_picture",
            "is_verified",
            "first_seen_at",
            "last_seen_at",
            "message_count",
        ],
    ),
    (
        "STREAM_SESSIONS",
        "stream_sessions",
        [
            "session_id",
            "channel_slug",
            "broadcaster_user_id",
            "title",
            "started_at",
            "ended_at",
            "is_live",
            "raw_payload",
            "ingested_at",
        ],
    ),
]

WEBHOOK_TABLE: tuple[str, str, list[str]] = (
    "WEBHOOK_EVENTS",
    "webhook_events",
    [
        "event_message_id",
        "event_type",
        "event_version",
        "subscription_id",
        "channel_slug",
        "received_at",
        "processed_ok",
        "error_message",
    ],
)

RAW_PAYLOAD_COLS = frozenset({"raw_payload"})


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or default).strip()


def _split_statements(sql: str) -> list[str]:
    lines: list[str] = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(line)
    return [p.strip() for p in "\n".join(lines).split(";") if p.strip()]


def _run_sql_file(cur: Any, path: Path) -> None:
    print(f"  Running {path.name}...")
    for stmt in _split_statements(path.read_text()):
        cur.execute(stmt)


def _load_private_key_bytes(pem: str, passphrase: str | None) -> bytes:
    from cryptography.hazmat.primitives import serialization

    normalized = pem.strip().replace("\\n", "\n")
    password = passphrase.encode("utf-8") if passphrase else None
    key = serialization.load_pem_private_key(
        normalized.encode("utf-8"),
        password=password,
    )
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def open_snowflake() -> Any:
    try:
        import snowflake.connector
    except ImportError as exc:
        raise SystemExit(
            "Install migrate deps: pip install -r requirements-migrate.txt"
        ) from exc

    account = _env("SNOWFLAKE_ACCOUNT")
    user = _env("SNOWFLAKE_USER")
    if not account or not user:
        raise SystemExit("Set SNOWFLAKE_ACCOUNT and SNOWFLAKE_USER for migration.")

    kwargs: dict[str, Any] = {
        "account": account,
        "user": user,
        "warehouse": _env("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        "database": _env("SNOWFLAKE_DATABASE", "KICK_CHAT"),
        "schema": _env("SNOWFLAKE_SCHEMA", "CORE"),
        "role": _env("SNOWFLAKE_ROLE", "SYSADMIN"),
    }
    private_key = _env("SNOWFLAKE_PRIVATE_KEY")
    if private_key:
        kwargs["private_key"] = _load_private_key_bytes(
            private_key,
            _env("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE") or None,
        )
    elif _env("SNOWFLAKE_PASSWORD"):
        kwargs["password"] = _env("SNOWFLAKE_PASSWORD")
    else:
        raise SystemExit("Set SNOWFLAKE_PRIVATE_KEY or SNOWFLAKE_PASSWORD.")

    return snowflake.connector.connect(**kwargs)


def _normalize_value(col: str, value: Any) -> Any:
    if value is None:
        return None
    if col == "raw_payload":
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        if isinstance(value, str):
            return value
        return json.dumps(value)
    return value


def _pretty(n: int) -> str:
    for unit, div in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if n >= div:
            return f"{n / div:.2f} {unit}"
    return f"{n} B"


def count_table(cur: Any, table: str) -> int:
    cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
    row = cur.fetchone()
    if isinstance(row, dict):
        return int(row["c"])
    return int(row[0])


def iter_snowflake_rows(
    sf_cur: Any, table: str, columns: list[str], *, fetch_size: int
) -> Iterator[tuple[Any, ...]]:
    col_sql = ", ".join(c.upper() for c in columns)
    sf_cur.execute(f"SELECT {col_sql} FROM {table}")
    while True:
        batch = sf_cur.fetchmany(fetch_size)
        if not batch:
            break
        for row in batch:
            yield tuple(_normalize_value(columns[i], row[i]) for i in range(len(columns)))


def copy_table(
    sf_conn: Any,
    pg_conn: Any,
    *,
    sf_table: str,
    pg_table: str,
    columns: list[str],
    dry_run: bool,
    batch_size: int,
    sleep_ms: int,
    max_db_bytes: int,
    drop_raw_payload: bool,
) -> tuple[int, int]:
    cols = [c for c in columns if not (drop_raw_payload and c in RAW_PAYLOAD_COLS)]
    sf_cur = sf_conn.cursor()
    try:
        sf_count = count_table(sf_cur, sf_table)
    finally:
        sf_cur.close()

    if dry_run:
        note = " (no raw_payload)" if drop_raw_payload and any(
            c in RAW_PAYLOAD_COLS for c in columns
        ) else ""
        print(f"  {sf_table} → {pg_table}: would copy {sf_count} rows{note}")
        return sf_count, 0

    cast_placeholders = [
        "%s::jsonb" if c == "raw_payload" else "%s" for c in cols
    ]
    sql = f"""
        INSERT INTO {pg_table} ({', '.join(cols)})
        VALUES ({', '.join(cast_placeholders)})
        ON CONFLICT DO NOTHING
    """

    sf_cur = sf_conn.cursor()
    batches = 0
    try:
        batch: list[tuple[Any, ...]] = []
        for row in iter_snowflake_rows(sf_cur, sf_table, cols, fetch_size=batch_size):
            batch.append(row)
            if len(batch) >= batch_size:
                with pg_conn.cursor() as pg_cur:
                    pg_cur.executemany(sql, batch)
                pg_conn.commit()
                batches += 1
                batch.clear()
                if sleep_ms > 0:
                    time.sleep(sleep_ms / 1000.0)
                size = database_size_bytes(pg_conn)
                if size >= max_db_bytes:
                    raise SystemExit(
                        f"Abort: Postgres size {_pretty(size)} >= limit "
                        f"{_pretty(max_db_bytes)}. Reclaim space or raise --max-db-gb."
                    )
                if batches % 25 == 0:
                    print(f"    {pg_table}: {batches} batches, db={_pretty(size)}")
        if batch:
            with pg_conn.cursor() as pg_cur:
                pg_cur.executemany(sql, batch)
            pg_conn.commit()
    finally:
        sf_cur.close()

    with pg_conn.cursor() as pg_cur:
        pg_count = count_table(pg_cur, pg_table)

    print(
        f"  {sf_table} → {pg_table}: snowflake={sf_count} postgres={pg_count} "
        f"db={_pretty(database_size_bytes(pg_conn))}"
    )
    return sf_count, pg_count


def apply_postgres_schema() -> None:
    print("Applying Postgres DDL/views...")
    with open_connection() as conn:
        with conn.cursor() as cur:
            for path in SQL_CORE:
                _run_sql_file(cur, path)
        conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate Snowflake CORE → Postgres")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-ddl", action="store_true")
    parser.add_argument(
        "--include-webhook-events",
        action="store_true",
        help="Also copy WEBHOOK_EVENTS (large; usually skip on 5GB plans)",
    )
    parser.add_argument(
        "--include-raw-payload",
        action="store_true",
        help="Copy raw_payload JSON (large; default skips it)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Rows per commit (default 100 — gentle on Railway)",
    )
    parser.add_argument(
        "--sleep-ms",
        type=int,
        default=50,
        help="Pause between batches in ms (default 50)",
    )
    parser.add_argument(
        "--max-db-gb",
        type=float,
        default=4.0,
        help="Abort if Postgres size reaches this many GiB (default 4.0)",
    )
    args = parser.parse_args()

    if not _env("DATABASE_URL"):
        print("DATABASE_URL is required.", file=sys.stderr)
        return 1

    max_db_bytes = int(args.max_db_gb * 1024**3)
    tables = list(CORE_TABLES)
    if args.include_webhook_events:
        tables.append(WEBHOOK_TABLE)
    else:
        print("Skipping WEBHOOK_EVENTS (pass --include-webhook-events to copy).")
    if not args.include_raw_payload:
        print("Skipping raw_payload columns (pass --include-raw-payload to copy).")

    if not args.skip_ddl and not args.dry_run:
        apply_postgres_schema()

    print("Connecting to Snowflake...")
    sf_conn = open_snowflake()
    try:
        print("Connecting to Postgres...")
        with db_connection() as pg_conn:
            if not args.dry_run:
                print(f"Postgres size now: {_pretty(database_size_bytes(pg_conn))}")
            print(
                f"Copying with batch={args.batch_size} sleep_ms={args.sleep_ms} "
                f"max_db={args.max_db_gb}GiB..."
            )
            for sf_table, pg_table, columns in tables:
                copy_table(
                    sf_conn,
                    pg_conn,
                    sf_table=sf_table,
                    pg_table=pg_table,
                    columns=columns,
                    dry_run=args.dry_run,
                    batch_size=max(10, args.batch_size),
                    sleep_ms=max(0, args.sleep_ms),
                    max_db_bytes=max_db_bytes,
                    drop_raw_payload=not args.include_raw_payload,
                )
    finally:
        sf_conn.close()

    print("Done.")
    if not args.dry_run:
        print(
            "\nIf disk is high: PYTHONPATH=. python scripts/reclaim_postgres_space.py\n"
            "Next: remove SNOWFLAKE_* from Railway, redeploy, then:\n"
            "  ALTER WAREHOUSE COMPUTE_WH SUSPEND;"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

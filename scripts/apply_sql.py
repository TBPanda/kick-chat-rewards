#!/usr/bin/env python3
"""Apply Snowflake DDL + views using credentials from .env."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.config import get_settings  # noqa: E402
from ingest.snowflake_writer import snowflake_connection  # noqa: E402

SQL_CORE = [
    ROOT / "sql" / "001_ddl.sql",
    ROOT / "sql" / "002_views.sql",
    ROOT / "sql" / "003_mcp.sql",
    ROOT / "sql" / "006_row_access_policies.sql",
]

SQL_MIGRATE = ROOT / "sql" / "005_migrate_amirphanthom_to_core.sql"


def split_statements(sql: str) -> list[str]:
    """Naive split on semicolons; strips comments starting with --."""
    lines: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        lines.append(line)
    text = "\n".join(lines)
    parts = [p.strip() for p in text.split(";")]
    return [p for p in parts if p]


def run_file(cur: object, path: Path) -> None:
    print(f"Running {path.name}...")
    for stmt in split_statements(path.read_text()):
        cur.execute(stmt)  # type: ignore[attr-defined]
    print(f"  OK ({path.name})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply Kick Chat Snowflake SQL")
    parser.add_argument(
        "--migrate-legacy",
        action="store_true",
        help="Also run 005_migrate_amirphanthom_to_core.sql (requires AMIRPHANTHOM schema)",
    )
    args = parser.parse_args()

    settings = get_settings()
    print(
        f"Connecting to {settings.snowflake_account} "
        f"db={settings.snowflake_database}.{settings.snowflake_schema}"
    )
    with snowflake_connection(settings) as conn:
        cur = conn.cursor()
        try:
            # DDL/migration needs schema create privileges (SYSADMIN may lack them)
            cur.execute("USE ROLE ACCOUNTADMIN")
            print("Using role ACCOUNTADMIN for DDL")
            for path in SQL_CORE:
                if not path.exists():
                    print(f"Skip missing {path.name}")
                    continue
                run_file(cur, path)
            if args.migrate_legacy:
                if SQL_MIGRATE.exists():
                    run_file(cur, SQL_MIGRATE)
                else:
                    print("Skip missing 005_migrate_amirphanthom_to_core.sql")
            conn.commit()
        finally:
            cur.close()
    print("Done.")
    if settings.snowflake_schema.upper() != "CORE":
        print(
            f"Warning: SNOWFLAKE_SCHEMA={settings.snowflake_schema!r}; "
            "set SNOWFLAKE_SCHEMA=CORE for multi-channel."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

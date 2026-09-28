#!/usr/bin/env python3
"""Apply Snowflake DDL + views using credentials from .env."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.config import get_settings  # noqa: E402
from ingest.snowflake_writer import snowflake_connection  # noqa: E402

SQL_FILES = [
    ROOT / "sql" / "001_ddl.sql",
    ROOT / "sql" / "002_views.sql",
    ROOT / "sql" / "003_mcp.sql",
]


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


def main() -> int:
    settings = get_settings()
    print(
        f"Connecting to {settings.snowflake_account} "
        f"db={settings.snowflake_database}.{settings.snowflake_schema}"
    )
    with snowflake_connection(settings) as conn:
        cur = conn.cursor()
        try:
            for path in SQL_FILES:
                if not path.exists():
                    print(f"Skip missing {path.name}")
                    continue
                print(f"Running {path.name}...")
                for stmt in split_statements(path.read_text()):
                    cur.execute(stmt)
                print(f"  OK ({path.name})")
            conn.commit()
        finally:
            cur.close()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

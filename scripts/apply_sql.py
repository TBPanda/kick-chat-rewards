#!/usr/bin/env python3
"""Apply Postgres DDL + views using DATABASE_URL from .env."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingest.config import get_settings  # noqa: E402
from ingest.db import db_connection  # noqa: E402

SQL_CORE = [
    ROOT / "sql" / "001_ddl.sql",
    ROOT / "sql" / "002_views.sql",
]


def split_statements(sql: str) -> list[str]:
    """Naive split on semicolons; strips full-line comments starting with --."""
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
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL is not set. Add Railway Postgres or a local URL.", file=sys.stderr)
        return 1

    # Redact password in log
    safe = settings.database_url.split("@")[-1] if "@" in settings.database_url else "(local)"
    print(f"Connecting to Postgres @ {safe}")
    with db_connection(settings) as conn:
        with conn.cursor() as cur:
            for path in SQL_CORE:
                if not path.exists():
                    print(f"Skip missing {path.name}")
                    continue
                run_file(cur, path)
        conn.commit()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

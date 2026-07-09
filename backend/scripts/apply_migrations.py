#!/usr/bin/env python3
"""Apply MySQL migrations to the database from settings / .env."""

from __future__ import annotations

import sys
from pathlib import Path

import pymysql
from pymysql.constants import CLIENT

# Allow running from repo without install
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "src"))

from memory_engine.config import get_settings  # noqa: E402

MIGRATIONS = BACKEND / "migrations" / "mysql"
FILES = (
    "001_initial_schema.sql",
    "002_seed_dev.sql",
    "003_seed_dreaming_job.sql",
)


def main() -> int:
    settings = get_settings()
    print(f"Target database: {settings.mysql_database} @ {settings.mysql_host}")
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="utf8mb4",
        client_flag=CLIENT.MULTI_STATEMENTS,
        autocommit=True,
    )
    cur = conn.cursor()
    for name in FILES:
        path = MIGRATIONS / name
        print(f"Applying {name} ...")
        cur.execute(path.read_text(encoding="utf-8"))
        while cur.nextset():
            pass
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s",
        (settings.mysql_database,),
    )
    print(f"Tables in {settings.mysql_database}: {cur.fetchone()[0]}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Create a temporary tenant DB and verify the baseline schema materializes.

The script is intentionally self-cleaning: it creates a database named
``aman_schema_check_<pid>``, applies ``apply_tenant_schema()``, compares actual
information_schema columns against historical migration expectations, and then
drops only that temporary database.
"""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from config import settings  # noqa: E402
from db_ddl.tenant_runner import apply_tenant_schema  # noqa: E402
from scripts.check_tenant_schema_completeness import (  # noqa: E402
    ALEMBIC_DIRS,
    extract_expected_from_migration,
    merge,
)


def _safe_temp_company_id() -> str:
    company_id = f"schema_check_{os.getpid()}"
    if not re.fullmatch(r"[a-z0-9_]+", company_id):
        raise RuntimeError("Unsafe temporary company id")
    return company_id


def _create_database(conn: Connection, db_name: str) -> None:
    conn.execute(text(f'CREATE DATABASE "{db_name}"'))


def _drop_database(conn: Connection, db_name: str) -> None:
    conn.execute(
        text(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = :db_name AND pid <> pg_backend_pid()
            """
        ),
        {"db_name": db_name},
    )
    conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))


def _expected_columns() -> dict[str, set[str]]:
    expected: dict[str, set[str]] = defaultdict(set)
    for directory in ALEMBIC_DIRS:
        for path in sorted(directory.glob("*.py")):
            merge(expected, extract_expected_from_migration(path))
    return expected


def _actual_columns(conn: Connection) -> dict[str, set[str]]:
    rows = conn.execute(
        text(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            """
        )
    ).fetchall()
    actual: dict[str, set[str]] = {}
    for table, column in rows:
        actual.setdefault(str(table).lower(), set()).add(str(column).lower())
    return actual


def main() -> int:
    company_id = _safe_temp_company_id()
    db_name = f"aman_{company_id}"
    admin_engine = create_engine(settings.DATABASE_URL, isolation_level="AUTOCOMMIT")
    tenant_engine = None
    created_database = False

    try:
        with admin_engine.connect() as conn:
            _drop_database(conn, db_name)
            _create_database(conn, db_name)
            created_database = True

        tenant_engine = create_engine(settings.get_company_database_url(company_id), isolation_level="AUTOCOMMIT")
        with tenant_engine.connect() as conn:
            apply_tenant_schema(conn)
            actual = _actual_columns(conn)

        expected = _expected_columns()
        missing: list[tuple[str, str]] = []
        for table, columns in sorted(expected.items()):
            for column in sorted(columns):
                if table not in actual or column not in actual[table]:
                    missing.append((table, column))

        print(f"temporary_database={db_name}")
        print(f"actual_tables={len(actual)}")
        print(f"actual_columns={sum(len(cols) for cols in actual.values())}")
        print(f"missing_columns={len(missing)}")
        for table, column in missing:
            print(f"MISSING {table}.{column}")
        return 1 if missing else 0
    except Exception as exc:
        print(f"temporary_database={db_name}")
        print(f"bootstrap_check_error={exc.__class__.__name__}")
        return 2
    finally:
        if tenant_engine is not None:
            tenant_engine.dispose()
        if created_database:
            try:
                with admin_engine.connect() as conn:
                    _drop_database(conn, db_name)
            except Exception as exc:
                print(f"cleanup_warning={exc.__class__.__name__}")
        admin_engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

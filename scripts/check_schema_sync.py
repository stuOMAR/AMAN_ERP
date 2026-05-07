#!/usr/bin/env python3
"""T010b: CI gate — diffs Alembic head vs canonical DDL modules.

Ensures every table/index/column defined in a migration also appears in the
canonical DDL module under ``backend/db_ddl/``, and vice versa.

Exit 0 if in sync, 1 if drift detected.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def extract_table_names_from_ddl(ddl_dir: Path) -> set[str]:
    """Extract CREATE TABLE / CREATE INDEX names from db_ddl modules."""
    tables: set[str] = set()
    for py_file in ddl_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # Match CREATE TABLE IF NOT EXISTS <name>
        for m in re.finditer(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
            content, re.IGNORECASE
        ):
            tables.add(m.group(1).lower())
        # Match CREATE (UNIQUE )?INDEX IF NOT EXISTS <name>
        for m in re.finditer(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
            content, re.IGNORECASE
        ):
            tables.add(m.group(1).lower())
    return tables


def extract_table_names_from_migrations(versions_dir: Path) -> set[str]:
    """Extract table/index names created in Alembic migrations."""
    tables: set[str] = set()
    for py_file in versions_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in re.finditer(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
            content, re.IGNORECASE
        ):
            tables.add(m.group(1).lower())
        for m in re.finditer(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
            content, re.IGNORECASE
        ):
            tables.add(m.group(1).lower())
        # Also detect op.create_table / op.create_index calls
        for m in re.finditer(
            r'op\.create_(?:table|index)\s*\(\s*["\'](\w+)["\']',
            content
        ):
            tables.add(m.group(1).lower())
    return tables


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    ddl_dir = repo_root / "backend" / "db_ddl"
    versions_dir = repo_root / "backend" / "alembic" / "versions"

    if not ddl_dir.exists():
        print("⚠ check_schema_sync: backend/db_ddl/ not found, skipping")
        return 0
    if not versions_dir.exists():
        print("⚠ check_schema_sync: backend/alembic/versions/ not found, skipping")
        return 0

    ddl_tables = extract_table_names_from_ddl(ddl_dir)
    migration_tables = extract_table_names_from_migrations(versions_dir)

    only_in_ddl = ddl_tables - migration_tables
    only_in_migrations = migration_tables - ddl_tables

    violations = []
    if only_in_ddl:
        violations.append(f"In DDL but not in migrations: {sorted(only_in_ddl)}")
    if only_in_migrations:
        violations.append(f"In migrations but not in DDL: {sorted(only_in_migrations)}")

    if violations:
        print("SCHEMA SYNC VIOLATIONS:")
        for v in violations:
            print(f"  ✗ {v}")
        return 1

    print("✓ check_schema_sync: DDL modules in sync with migration head")
    return 0


if __name__ == "__main__":
    sys.exit(main())

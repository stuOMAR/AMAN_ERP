"""T7.1 + T7.6 — pg_trgm GIN indexes + missing FK indexes.

Revision: 0020_search_and_fk_indexes
Revises: 0019_returns_unified_view
Create Date: 2026-05-01

T7.1 — install pg_trgm and create GIN(gin_trgm_ops) indexes on hot search
columns (products, parties, invoices, etc.).

T7.6 — add B-tree indexes on referencing-side FK columns that PostgreSQL
doesn't auto-index, so cascade deletes and joins use Index Scan.

The actual lists (PHASE7_TRGM_INDEXES, PHASE7_FK_INDEXES) and the helper
SQL builders live in ``db_ddl/tenant_runner.py`` so the same definitions
are applied to fresh tenants by ``apply_tenant_schema``. This migration
only re-uses them so existing tenants get the indexes via
``alembic upgrade head``.

Every CREATE INDEX is wrapped in ``IF NOT EXISTS`` and a column-existence
guard, making the migration fully idempotent and safe on partial schemas.
"""

import os
import sys

from alembic import op


revision = "0020_search_and_fk_indexes"
down_revision = "0019_returns_unified_view"
branch_labels = None
depends_on = None


def _ensure_backend_on_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.abspath(os.path.join(here, "..", ".."))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)


def upgrade() -> None:
    _ensure_backend_on_path()
    from db_ddl.tenant_runner import (
        PHASE7_FK_INDEXES,
        PHASE7_TRGM_INDEXES,
        _PG_TRGM_EXTENSION_SQL,
        _fk_index_sql,
        _trgm_index_sql,
    )

    op.execute(_PG_TRGM_EXTENSION_SQL)
    for table, column, idx in PHASE7_TRGM_INDEXES:
        op.execute(_trgm_index_sql(table, column, idx))
    for table, column, idx in PHASE7_FK_INDEXES:
        op.execute(_fk_index_sql(table, column, idx))


def downgrade() -> None:
    _ensure_backend_on_path()
    from db_ddl.tenant_runner import (
        PHASE7_FK_INDEXES,
        PHASE7_TRGM_INDEXES,
    )
    for _, _, idx in PHASE7_TRGM_INDEXES + PHASE7_FK_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {idx}")

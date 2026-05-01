"""Complete baseline — full schema snapshot via db_ddl/tenant_runner.

Revision ID: 0001_baseline_complete
Revises:
Create Date: 2026-04-17 (T6.4 update: 2026-05-01)

T6.4: All per-tenant DDL was extracted from ``backend/database.py`` into
``backend/db_ddl/tenant_schema.py`` (string builders) and
``backend/db_ddl/tenant_runner.py`` (orchestrator). This migration is the
canonical entry point for fresh-tenant schema creation. Running

    alembic -x company=<id> upgrade head

against an empty tenant database produces the **complete** schema by
calling :func:`db_ddl.tenant_runner.apply_tenant_schema`.

Idempotency: every CREATE uses ``IF NOT EXISTS`` and every constraint is
guarded, so re-running on an existing tenant is a no-op.
"""

import os
import sys

from alembic import op


# revision identifiers, used by Alembic.
revision = "0001_baseline_complete"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the full per-tenant schema to the currently-bound tenant DB."""
    # Make ``backend`` importable when this migration runs from the Alembic
    # CLI; defensive for both ``cwd=backend/`` and ``cwd=<repo root>``.
    here = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.abspath(os.path.join(here, "..", ".."))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from db_ddl.tenant_runner import apply_tenant_schema  # noqa: E402

    bind = op.get_bind()
    apply_tenant_schema(bind, currency="SAR")


def downgrade() -> None:
    # Dropping all tables is intentionally not implemented.
    # To reset a tenant DB, drop and recreate the database.
    pass

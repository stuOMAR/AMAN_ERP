"""projects/expenses/time idempotency guards

Revision ID: 030g_projects_expenses_time_idempotency
Revises: 030f_inventory_idempotency_guards
Create Date: 2026-05-21
"""
from typing import Sequence, Union

from alembic import op


revision: str = "030g_projects_expenses_time_idempotency"
down_revision: Union[str, None] = "030f_inventory_idempotency_guards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tables = [
        "expenses",
        "project_expenses",
        "project_revenues",
        "project_change_orders",
        "timesheet_entries",
        "resource_allocations",
    ]
    for table in tables:
        op.execute(f"""
            ALTER TABLE {table}
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
        """)
        op.execute(f"""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_{table}_idempotency_key
            ON {table} (idempotency_key)
            WHERE idempotency_key IS NOT NULL
        """)

    op.execute("""
        ALTER TABLE expenses
        ADD COLUMN IF NOT EXISTS approval_idempotency_key VARCHAR(64)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_expenses_approval_idempotency_key
        ON expenses (approval_idempotency_key)
        WHERE approval_idempotency_key IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_expenses_approval_idempotency_key")
    op.execute("ALTER TABLE expenses DROP COLUMN IF EXISTS approval_idempotency_key")
    for table in [
        "resource_allocations",
        "timesheet_entries",
        "project_change_orders",
        "project_revenues",
        "project_expenses",
        "expenses",
    ]:
        op.execute(f"DROP INDEX IF EXISTS uq_{table}_idempotency_key")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS idempotency_key")

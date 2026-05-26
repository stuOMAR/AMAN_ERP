"""hr: add idempotency_key to leave_requests, salary_advances, payroll_entries

Revision ID: 031a_hr_idempotency_keys
Revises: 030l_audit_logs_branch_id_fk_remove
Create Date: 2026-05-24

Prevents duplicate submissions for HR/Payroll transactions.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "031a_hr_idempotency_keys"
down_revision: Union[str, None] = "030l_audit_logs_branch_id_fk_remove"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add idempotency_key column to leave_requests
    op.execute("""
        ALTER TABLE leave_requests
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_leave_requests_idempotency_key
        ON leave_requests (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)

    # 2. Add idempotency_key column to salary_advances
    op.execute("""
        ALTER TABLE salary_advances
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_salary_advances_idempotency_key
        ON salary_advances (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)

    # 3. Add idempotency_key column to payroll_entries
    op.execute("""
        ALTER TABLE payroll_entries
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_entries_idempotency_key
        ON payroll_entries (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_payroll_entries_idempotency_key")
    op.execute("ALTER TABLE payroll_entries DROP COLUMN IF EXISTS idempotency_key")

    op.execute("DROP INDEX IF EXISTS uq_salary_advances_idempotency_key")
    op.execute("ALTER TABLE salary_advances DROP COLUMN IF EXISTS idempotency_key")

    op.execute("DROP INDEX IF EXISTS uq_leave_requests_idempotency_key")
    op.execute("ALTER TABLE leave_requests DROP COLUMN IF EXISTS idempotency_key")

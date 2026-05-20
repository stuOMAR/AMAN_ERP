"""Add payroll period overlap exclusion constraint and unique payslip constraint.

Revision ID: 0034_payroll_period_overlap_constraint
Revises: 0033_accounts_currency_backfill
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0034_payroll_period_overlap_constraint"
down_revision = "0033_accounts_currency_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add state column to payroll_periods if missing
    op.execute("""
        ALTER TABLE payroll_periods
            ADD COLUMN IF NOT EXISTS state VARCHAR(20) DEFAULT 'draft'
            CHECK (state IN ('draft', 'calculated', 'locked', 'reversed'))
    """)

    # Add tenant_id to payroll_periods if missing
    op.execute("""
        ALTER TABLE payroll_periods
            ADD COLUMN IF NOT EXISTS tenant_id INTEGER
    """)

    # Unique constraint to prevent duplicate payslips per employee per period
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_entries_period_employee
        ON payroll_entries (period_id, employee_id)
    """)

    # Exclusion constraint to prevent overlapping non-reversed payroll periods
    # Requires btree_gist extension (already enabled in GL integrity guards)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'excl_payroll_periods_nooverlap'
            ) THEN
                ALTER TABLE payroll_periods
                    ADD CONSTRAINT excl_payroll_periods_nooverlap
                    EXCLUDE USING GIST (
                        COALESCE(tenant_id, 0) WITH =,
                        daterange(start_date::date, end_date::date, '[]') WITH &&
                    )
                    WHERE (COALESCE(state, 'draft') <> 'reversed');
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_payroll_entries_period_employee")
    op.execute("""
        ALTER TABLE payroll_periods
            DROP CONSTRAINT IF EXISTS excl_payroll_periods_nooverlap
    """)

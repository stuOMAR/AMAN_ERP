"""Payroll entries period_id alignment.

Feature 024 — T022. Ensures payroll_entries.period_id exists with FK.
"""
from alembic import op
import sqlalchemy as sa

revision = "024g_payroll_entries_period_id_align"
down_revision = "024f_bank_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add period_id if not exists (may already be present in some tenants)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'payroll_entries' AND column_name = 'period_id'
            ) THEN
                ALTER TABLE payroll_entries ADD COLUMN period_id BIGINT;
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'fk_payroll_entries_period'
            ) THEN
                ALTER TABLE payroll_entries
                ADD CONSTRAINT fk_payroll_entries_period
                FOREIGN KEY (period_id) REFERENCES payroll_periods(id);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_constraint("fk_payroll_entries_period", "payroll_entries", type_="foreignkey")
    op.drop_column("payroll_entries", "period_id")

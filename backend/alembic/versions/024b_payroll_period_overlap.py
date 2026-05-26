"""Payroll period overlap prevention.

Feature 024 — T011. Adds state column + tstzrange exclusion constraint.
"""
from alembic import op
import sqlalchemy as sa

revision = "024b_payroll_period_overlap"
down_revision = "024a_hr_pii_encryption"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # Perform column addition and exclusion constraint conditionally
    op.execute("""
        DO $$
        DECLARE
            has_tenant_id boolean;
        BEGIN
            -- 1. Add state column if not exists
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'payroll_periods' AND column_name = 'state'
            ) THEN
                ALTER TABLE payroll_periods ADD COLUMN state VARCHAR(16) NOT NULL DEFAULT 'draft';
            END IF;

            -- 2. Add exclusion constraint if not exists
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints 
                WHERE constraint_name = 'excl_payroll_period_overlap'
            ) THEN
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'payroll_periods' AND column_name = 'tenant_id'
                ) INTO has_tenant_id;

                IF has_tenant_id THEN
                    ALTER TABLE payroll_periods
                    ADD CONSTRAINT excl_payroll_period_overlap
                    EXCLUDE USING gist (
                        tenant_id WITH =,
                        daterange(start_date, end_date, '[]') WITH &&
                    ) WHERE (state <> 'reversed');
                ELSE
                    ALTER TABLE payroll_periods
                    ADD CONSTRAINT excl_payroll_period_overlap
                    EXCLUDE USING gist (
                        daterange(start_date, end_date, '[]') WITH &&
                    ) WHERE (state <> 'reversed');
                END IF;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE payroll_periods DROP CONSTRAINT IF EXISTS excl_payroll_period_overlap")
    op.execute("ALTER TABLE payroll_periods DROP COLUMN IF EXISTS state")

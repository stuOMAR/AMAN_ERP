"""Payroll run reversal state.

Feature 024 — T020. Adds wps_superseded_by_run_id to payroll_runs.
"""
from alembic import op
import sqlalchemy as sa

revision = "024c_payroll_period_reversal_state"
down_revision = "024b_payroll_period_overlap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'payroll_runs') THEN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'payroll_runs' AND column_name = 'wps_superseded_by_run_id'
                ) THEN
                    ALTER TABLE payroll_runs ADD COLUMN wps_superseded_by_run_id BIGINT;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints 
                    WHERE constraint_name = 'fk_payroll_runs_superseded'
                ) THEN
                    ALTER TABLE payroll_runs 
                    ADD CONSTRAINT fk_payroll_runs_superseded 
                    FOREIGN KEY (wps_superseded_by_run_id) REFERENCES payroll_runs(id);
                END IF;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'payroll_runs') THEN
                ALTER TABLE payroll_runs DROP CONSTRAINT IF EXISTS fk_payroll_runs_superseded;
                ALTER TABLE payroll_runs DROP COLUMN IF EXISTS wps_superseded_by_run_id;
            END IF;
        END $$;
        """
    )

"""023l: Workstation overhead rate + effective dating.

Revision: 023l_workstation_overhead
Revises: 023d_acc_map_sales_consolidation
Create Date: 2026-05-02
"""
from alembic import op


revision = "023l_workstation_overhead"
down_revision = "023d_acc_map_sales_consolidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workstations (
            id             BIGSERIAL      PRIMARY KEY,
            tenant_id      BIGINT,
            name           VARCHAR(255),
            code           VARCHAR(64),
            overhead_rate  NUMERIC(18,4),
            effective_from DATE,
            effective_to   DATE,
            created_at     TIMESTAMPTZ    NOT NULL DEFAULT clock_timestamp(),
            updated_at     TIMESTAMPTZ    NOT NULL DEFAULT clock_timestamp()
        );

        ALTER TABLE workstations
            ADD COLUMN IF NOT EXISTS overhead_rate NUMERIC(18,4),
            ADD COLUMN IF NOT EXISTS effective_from DATE,
            ADD COLUMN IF NOT EXISTS effective_to DATE;

        -- EXCLUSION constraint to prevent overlapping effective ranges
        -- Requires btree_gist extension
        CREATE EXTENSION IF NOT EXISTS btree_gist;

        DO $$ BEGIN
            ALTER TABLE workstations
                ADD CONSTRAINT excl_workstation_effective_range
                EXCLUDE USING gist (
                    id WITH =,
                    daterange(effective_from, effective_to, '[]') WITH &&
                );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE workstations
            DROP CONSTRAINT IF EXISTS excl_workstation_effective_range;
        ALTER TABLE workstations
            DROP COLUMN IF EXISTS effective_to,
            DROP COLUMN IF EXISTS effective_from,
            DROP COLUMN IF EXISTS overhead_rate;
        """
    )

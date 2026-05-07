"""023j: BOM snapshots + manufacturing order extensions.

Revision: 023j_bom_snapshots_and_mo_extensions
Revises: 023d_acc_map_sales_consolidation
Create Date: 2026-05-02
"""
from alembic import op


revision = "023j_bom_snapshots_and_mo_extensions"
down_revision = "023d_acc_map_sales_consolidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- 1. BOM snapshots
        CREATE TABLE IF NOT EXISTS bom_snapshots (
            id              BIGSERIAL       PRIMARY KEY,
            tenant_id       BIGINT          NOT NULL,
            mo_id           BIGINT          NOT NULL UNIQUE,
            bom_id          BIGINT          NOT NULL,
            bom_version     INT             NOT NULL,
            payload         JSONB           NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
        );

        -- 2. Extend manufacturing_orders
        ALTER TABLE manufacturing_orders
            ADD COLUMN IF NOT EXISTS bom_snapshot_id BIGINT,
            ADD COLUMN IF NOT EXISTS remaining_qty NUMERIC(18,4),
            ADD COLUMN IF NOT EXISTS qc_required BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS requires_approval BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS approved_by BIGINT,
            ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;

        -- FK to bom_snapshots
        DO $$ BEGIN
            ALTER TABLE manufacturing_orders
                ADD CONSTRAINT fk_mo_bom_snapshot
                FOREIGN KEY (bom_snapshot_id) REFERENCES bom_snapshots(id);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;

        -- Backfill remaining_qty
        UPDATE manufacturing_orders
        SET remaining_qty = COALESCE(original_qty, planned_qty, 0) - COALESCE(completed_qty, 0)
        WHERE remaining_qty IS NULL;

        -- Extend state CHECK
        ALTER TABLE manufacturing_orders
            DROP CONSTRAINT IF EXISTS chk_mo_state;
        ALTER TABLE manufacturing_orders
            ADD CONSTRAINT chk_mo_state
            CHECK (state IN ('planned','pending_approval','released','in_progress','qc_pending','completed','cancelled'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE manufacturing_orders
            DROP CONSTRAINT IF EXISTS chk_mo_state;
        ALTER TABLE manufacturing_orders
            DROP CONSTRAINT IF EXISTS fk_mo_bom_snapshot;
        ALTER TABLE manufacturing_orders
            DROP COLUMN IF EXISTS approved_at,
            DROP COLUMN IF EXISTS approved_by,
            DROP COLUMN IF EXISTS requires_approval,
            DROP COLUMN IF EXISTS qc_required,
            DROP COLUMN IF EXISTS remaining_qty,
            DROP COLUMN IF EXISTS bom_snapshot_id;
        DROP TABLE IF EXISTS bom_snapshots;
        """
    )

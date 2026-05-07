"""023k: Production completions + scrap movements.

Revision: 023k_production_completions_and_scrap
Revises: 023d_acc_map_sales_consolidation
Create Date: 2026-05-02
"""
from alembic import op


revision = "023k_production_completions_and_scrap"
down_revision = "023d_acc_map_sales_consolidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- 1. Production completions
        CREATE TABLE IF NOT EXISTS production_completions (
            id                      BIGSERIAL       PRIMARY KEY,
            tenant_id               BIGINT          NOT NULL,
            mo_id                   BIGINT          NOT NULL,
            qty                     NUMERIC(18,4)   NOT NULL,
            actual_material_cost    NUMERIC(18,4),
            actual_labor_cost       NUMERIC(18,4),
            actual_overhead_cost    NUMERIC(18,4),
            byproduct_allocation_method VARCHAR(20),
            wip_to_fg_je_id         BIGINT          NOT NULL,
            qc_state                VARCHAR(20),
            completed_at            TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
            created_at              TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
        );

        ALTER TABLE production_completions
            DROP CONSTRAINT IF EXISTS chk_pc_qc_state;
        ALTER TABLE production_completions
            ADD CONSTRAINT chk_pc_qc_state
            CHECK (qc_state IN ('pending','passed','failed','n/a'));

        CREATE INDEX IF NOT EXISTS ix_prod_completions_mo
            ON production_completions (tenant_id, mo_id, completed_at);

        -- 2. Scrap movements
        CREATE TABLE IF NOT EXISTS scrap_movements (
            id                  BIGSERIAL       PRIMARY KEY,
            tenant_id           BIGINT          NOT NULL,
            item_id             BIGINT          NOT NULL,
            warehouse_id        BIGINT          NOT NULL,
            qty                 NUMERIC(18,4)   NOT NULL,
            unit_cost_at_scrap  NUMERIC(18,4)   NOT NULL,
            reason              VARCHAR(64)     NOT NULL,
            mo_id               BIGINT,
            je_id               BIGINT          NOT NULL,
            occurred_at         TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
        );

        ALTER TABLE scrap_movements
            DROP CONSTRAINT IF EXISTS chk_scrap_reason;
        ALTER TABLE scrap_movements
            ADD CONSTRAINT chk_scrap_reason
            CHECK (reason IN ('mo_loss','qc_fail','expiry','damage','other'));

        CREATE INDEX IF NOT EXISTS ix_scrap_movements_item
            ON scrap_movements (tenant_id, item_id, occurred_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_scrap_movements_item;
        ALTER TABLE scrap_movements DROP CONSTRAINT IF EXISTS chk_scrap_reason;
        DROP TABLE IF EXISTS scrap_movements;
        DROP INDEX IF EXISTS ix_prod_completions_mo;
        ALTER TABLE production_completions DROP CONSTRAINT IF EXISTS chk_pc_qc_state;
        DROP TABLE IF EXISTS production_completions;
        """
    )

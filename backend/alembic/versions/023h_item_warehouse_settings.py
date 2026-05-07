"""023h: Item warehouse settings table.

Revision: 023h_item_warehouse_settings
Revises: 023d_acc_map_sales_consolidation
Create Date: 2026-05-02
"""
from alembic import op


revision = "023h_item_warehouse_settings"
down_revision = "023d_acc_map_sales_consolidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS item_warehouse_settings (
            tenant_id           BIGINT          NOT NULL,
            item_id             BIGINT          NOT NULL,
            warehouse_id        BIGINT          NOT NULL,
            reorder_point       NUMERIC(18,4),
            reorder_quantity    NUMERIC(18,4),
            safety_stock        NUMERIC(18,4),
            lead_time_days      INT,
            preferred_supplier_id BIGINT,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (tenant_id, item_id, warehouse_id)
        );

        -- Backfill from existing item-level reorder fields where present
        INSERT INTO item_warehouse_settings (tenant_id, item_id, warehouse_id, reorder_point, reorder_quantity)
        SELECT tenant_id, id, 0, reorder_level, reorder_qty
        FROM products
        WHERE reorder_level IS NOT NULL AND reorder_level > 0
        ON CONFLICT (tenant_id, item_id, warehouse_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS item_warehouse_settings;")

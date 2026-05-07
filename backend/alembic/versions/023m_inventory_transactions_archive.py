"""023m: Inventory transactions archive table.

Revision: 023m_inventory_transactions_archive
Revises: 023d_acc_map_sales_consolidation
Create Date: 2026-05-02
"""
from alembic import op


revision = "023m_inventory_transactions_archive"
down_revision = "023d_acc_map_sales_consolidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_transactions_archive (
            LIKE inventory_transactions INCLUDING DEFAULTS INCLUDING CONSTRAINTS
        );

        -- Mirror primary indexes for spanning queries
        CREATE INDEX IF NOT EXISTS ix_inv_txn_archive_item_wh
            ON inventory_transactions_archive (tenant_id, item_id, warehouse_id, occurred_at);

        CREATE INDEX IF NOT EXISTS ix_inv_txn_archive_tenant_date
            ON inventory_transactions_archive (tenant_id, occurred_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_inv_txn_archive_tenant_date;
        DROP INDEX IF EXISTS ix_inv_txn_archive_item_wh;
        DROP TABLE IF EXISTS inventory_transactions_archive;
        """
    )

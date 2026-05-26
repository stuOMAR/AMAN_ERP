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
        DO $$
        DECLARE
            col_tenant text := NULL;
            col_item text := NULL;
            col_date text := NULL;
        BEGIN
            -- 1. Create table if not exists
            IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'inventory_transactions_archive') THEN
                CREATE TABLE inventory_transactions_archive (
                    LIKE inventory_transactions INCLUDING DEFAULTS INCLUDING CONSTRAINTS
                );
            END IF;

            -- 2. Detect column names
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'inventory_transactions_archive' AND column_name = 'tenant_id') THEN
                col_tenant := 'tenant_id';
            END IF;

            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'inventory_transactions_archive' AND column_name = 'item_id') THEN
                col_item := 'item_id';
            ELSIF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'inventory_transactions_archive' AND column_name = 'product_id') THEN
                col_item := 'product_id';
            END IF;

            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'inventory_transactions_archive' AND column_name = 'occurred_at') THEN
                col_date := 'occurred_at';
            ELSIF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'inventory_transactions_archive' AND column_name = 'created_at') THEN
                col_date := 'created_at';
            END IF;

            -- 3. Create ix_inv_txn_archive_item_wh
            IF col_item IS NOT NULL AND col_date IS NOT NULL THEN
                IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_inv_txn_archive_item_wh') THEN
                    IF col_tenant IS NOT NULL THEN
                        EXECUTE 'CREATE INDEX ix_inv_txn_archive_item_wh ON inventory_transactions_archive (' || col_tenant || ', ' || col_item || ', warehouse_id, ' || col_date || ')';
                    ELSE
                        EXECUTE 'CREATE INDEX ix_inv_txn_archive_item_wh ON inventory_transactions_archive (' || col_item || ', warehouse_id, ' || col_date || ')';
                    END IF;
                END IF;
            END IF;

            -- 4. Create ix_inv_txn_archive_tenant_date
            IF col_date IS NOT NULL THEN
                IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'ix_inv_txn_archive_tenant_date') THEN
                    IF col_tenant IS NOT NULL THEN
                        EXECUTE 'CREATE INDEX ix_inv_txn_archive_tenant_date ON inventory_transactions_archive (' || col_tenant || ', ' || col_date || ')';
                    ELSE
                        EXECUTE 'CREATE INDEX ix_inv_txn_archive_tenant_date ON inventory_transactions_archive (' || col_date || ')';
                    END IF;
                END IF;
            END IF;
        END $$;
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

"""023c: Returns unified table + compatibility views.

Revision: 023c_returns_unified_table
Revises: 023b_sales_order_invoice_link
Create Date: 2026-05-02

Creates returns_unified + returns_unified_lines.
Migrates existing sales_returns/pos_returns rows.
Replaces originals with updatable views.
"""
from alembic import op


revision = "023c_returns_unified_table"
down_revision = "023b_sales_order_invoice_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- 1. Main returns table
        CREATE TABLE IF NOT EXISTS returns_unified (
            id                  BIGSERIAL       PRIMARY KEY,
            tenant_id           BIGINT          NOT NULL,
            source              VARCHAR(16)     NOT NULL,
            original_invoice_id BIGINT,
            original_pos_sale_id BIGINT,
            state               VARCHAR(20)     NOT NULL DEFAULT 'draft',
            restock_warehouse_id BIGINT,
            je_id               BIGINT,
            total_amount        NUMERIC(18,4)   NOT NULL DEFAULT 0,
            reason              TEXT,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
            created_by          BIGINT,
            updated_by          BIGINT,
            deleted_at          TIMESTAMPTZ
        );

        -- 2. Return lines
        CREATE TABLE IF NOT EXISTS returns_unified_lines (
            id          BIGSERIAL       PRIMARY KEY,
            tenant_id   BIGINT          NOT NULL,
            return_id   BIGINT          NOT NULL,
            line_no     INT             NOT NULL,
            item_id     BIGINT          NOT NULL,
            qty         NUMERIC(18,4)   NOT NULL,
            unit_price  NUMERIC(18,4)   NOT NULL,
            tax_id      BIGINT,
            tax_rate    NUMERIC(8,4),
            created_at  TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
        );

        -- Indexes
        CREATE INDEX IF NOT EXISTS ix_returns_unified_tenant
            ON returns_unified (tenant_id, state);
        CREATE INDEX IF NOT EXISTS ix_returns_unified_lines_return
            ON returns_unified_lines (tenant_id, return_id);

        -- Partial unique: only one draft return per original invoice
        CREATE UNIQUE INDEX IF NOT EXISTS uix_return_draft_invoice
            ON returns_unified (tenant_id, original_invoice_id)
            WHERE state = 'draft' AND original_invoice_id IS NOT NULL;

        -- Partial unique: only one draft return per original pos sale
        CREATE UNIQUE INDEX IF NOT EXISTS uix_return_draft_pos
            ON returns_unified (tenant_id, original_pos_sale_id)
            WHERE state = 'draft' AND original_pos_sale_id IS NOT NULL;

        -- 3. Migrate existing sales_returns data (if table exists)
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'sales_returns') THEN
                INSERT INTO returns_unified (tenant_id, source, original_invoice_id, state, total_amount, reason, created_at, created_by)
                SELECT tenant_id, 'sales', invoice_id, COALESCE(status, 'draft'), COALESCE(total_amount, 0), reason, created_at, created_by
                FROM sales_returns
                ON CONFLICT DO NOTHING;

                -- Replace with view
                DROP TABLE sales_returns;
                CREATE VIEW sales_returns AS
                SELECT id, tenant_id, original_invoice_id AS invoice_id, state AS status, total_amount, reason, created_at, created_by, updated_at
                FROM returns_unified WHERE source = 'sales' AND deleted_at IS NULL;
            END IF;
        END $$;

        -- 4. Migrate existing pos_returns data (if table exists)
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'pos_returns') THEN
                INSERT INTO returns_unified (tenant_id, source, original_pos_sale_id, state, total_amount, reason, created_at, created_by)
                SELECT tenant_id, 'pos', pos_sale_id, COALESCE(status, 'draft'), COALESCE(total_amount, 0), reason, created_at, created_by
                FROM pos_returns
                ON CONFLICT DO NOTHING;

                -- Replace with view
                DROP TABLE pos_returns;
                CREATE VIEW pos_returns AS
                SELECT id, tenant_id, original_pos_sale_id AS pos_sale_id, state AS status, total_amount, reason, created_at, created_by, updated_at
                FROM returns_unified WHERE source = 'pos' AND deleted_at IS NULL;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW IF EXISTS pos_returns;
        DROP VIEW IF EXISTS sales_returns;
        DROP INDEX IF EXISTS uix_return_draft_pos;
        DROP INDEX IF EXISTS uix_return_draft_invoice;
        DROP INDEX IF EXISTS ix_returns_unified_lines_return;
        DROP INDEX IF EXISTS ix_returns_unified_tenant;
        DROP TABLE IF EXISTS returns_unified_lines;
        DROP TABLE IF EXISTS returns_unified;
        """
    )

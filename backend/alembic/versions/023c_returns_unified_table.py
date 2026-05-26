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
        -- Safely drop view first to avoid DuplicateTable conflict when transitioning from view to table
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_class c 
                JOIN pg_namespace n ON n.oid = c.relnamespace 
                WHERE n.nspname = 'public' AND c.relname = 'returns_unified' AND c.relkind = 'v'
            ) THEN
                DROP VIEW returns_unified;
            END IF;
        END $$;

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
        DO $$ 
        DECLARE
            has_tenant_id boolean;
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'sales_returns') THEN
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'sales_returns' AND column_name = 'tenant_id'
                ) INTO has_tenant_id;
                
                IF has_tenant_id THEN
                    INSERT INTO returns_unified (id, tenant_id, source, original_invoice_id, state, total_amount, reason, created_at, created_by)
                    SELECT id, tenant_id, 'sales', invoice_id, COALESCE(status, 'draft'), COALESCE(refund_amount, total, 0), notes, created_at, created_by
                    FROM sales_returns
                    ON CONFLICT DO NOTHING;
                ELSE
                    INSERT INTO returns_unified (id, tenant_id, source, original_invoice_id, state, total_amount, reason, created_at, created_by)
                    SELECT id, current_setting('app.tenant_id', true)::bigint, 'sales', invoice_id, COALESCE(status, 'draft'), COALESCE(refund_amount, total, 0), notes, created_at, created_by
                    FROM sales_returns
                    ON CONFLICT DO NOTHING;
                END IF;

                -- Replace with view (CASCADE drops the sales_return_lines_return_id_fkey constraint)
                DROP TABLE sales_returns CASCADE;
                CREATE VIEW sales_returns AS
                SELECT id, current_setting('app.tenant_id', true)::bigint AS tenant_id, original_invoice_id AS invoice_id, state AS status, total_amount, reason, created_at, created_by, updated_at
                FROM returns_unified WHERE source = 'sales' AND deleted_at IS NULL;
            END IF;
        END $$;

        -- 4. Migrate existing pos_returns data (if table exists)
        DO $$ 
        DECLARE
            has_tenant_id boolean;
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'pos_returns') THEN
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'pos_returns' AND column_name = 'tenant_id'
                ) INTO has_tenant_id;
                
                IF has_tenant_id THEN
                    INSERT INTO returns_unified (id, tenant_id, source, original_pos_sale_id, state, total_amount, reason, created_at, created_by)
                    SELECT id, tenant_id, 'pos', original_order_id, 'completed', COALESCE(refund_amount, 0), notes, created_at, CASE WHEN created_by ~ '^[0-9]+$' THEN created_by::bigint ELSE NULL END
                    FROM pos_returns
                    ON CONFLICT DO NOTHING;
                ELSE
                    INSERT INTO returns_unified (id, tenant_id, source, original_pos_sale_id, state, total_amount, reason, created_at, created_by)
                    SELECT id, current_setting('app.tenant_id', true)::bigint, 'pos', original_order_id, 'completed', COALESCE(refund_amount, 0), notes, created_at, CASE WHEN created_by ~ '^[0-9]+$' THEN created_by::bigint ELSE NULL END
                    FROM pos_returns
                    ON CONFLICT DO NOTHING;
                END IF;

                -- Replace with view (CASCADE drops the pos_return_items_return_id_fkey constraint)
                DROP TABLE pos_returns CASCADE;
                CREATE VIEW pos_returns AS
                SELECT id, current_setting('app.tenant_id', true)::bigint AS tenant_id, original_pos_sale_id AS pos_sale_id, state AS status, total_amount, reason, created_at, created_by, updated_at
                FROM returns_unified WHERE source = 'pos' AND deleted_at IS NULL;
            END IF;
        END $$;

        -- 5. Restore foreign key constraints referencing physical returns_unified table
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'sales_return_lines') THEN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints 
                    WHERE constraint_name = 'sales_return_lines_return_id_fkey'
                ) THEN
                    ALTER TABLE sales_return_lines 
                    ADD CONSTRAINT sales_return_lines_return_id_fkey 
                    FOREIGN KEY (return_id) REFERENCES returns_unified(id) ON DELETE CASCADE;
                END IF;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'pos_return_items') THEN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints 
                    WHERE constraint_name = 'pos_return_items_return_id_fkey'
                ) THEN
                    ALTER TABLE pos_return_items 
                    ADD CONSTRAINT pos_return_items_return_id_fkey 
                    FOREIGN KEY (return_id) REFERENCES returns_unified(id) ON DELETE CASCADE;
                END IF;
            END IF;
        END $$;

        -- 6. Sync BIGSERIAL primary key sequence
        SELECT setval(pg_get_serial_sequence('returns_unified', 'id'), COALESCE(MAX(id), 1)) FROM returns_unified;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE IF EXISTS sales_return_lines DROP CONSTRAINT IF EXISTS sales_return_lines_return_id_fkey;
        ALTER TABLE IF EXISTS pos_return_items DROP CONSTRAINT IF EXISTS pos_return_items_return_id_fkey;
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

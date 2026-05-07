"""023d: Consolidate acc_map_sales with direction column.

Revision: 023d_acc_map_sales_consolidation
Revises: 023c_returns_unified_table
Create Date: 2026-05-02

Adds direction column to acc_map_sales, copies acc_map_sales_rev rows,
replaces acc_map_sales_rev with a view.
"""
from alembic import op


revision = "023d_acc_map_sales_consolidation"
down_revision = "023c_returns_unified_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- 0. Ensure base table exists for tenants that predate sales mapping DDL
        CREATE TABLE IF NOT EXISTS acc_map_sales (
            id           BIGSERIAL      PRIMARY KEY,
            tenant_id    BIGINT,
            mapping_key  VARCHAR(64)    NOT NULL,
            account_code VARCHAR(64)    NOT NULL,
            direction    VARCHAR(16)    NOT NULL DEFAULT 'forward',
            created_at   TIMESTAMPTZ    NOT NULL DEFAULT clock_timestamp(),
            updated_at   TIMESTAMPTZ    NOT NULL DEFAULT clock_timestamp()
        );

        -- 1. Add direction column
        ALTER TABLE acc_map_sales
            ADD COLUMN IF NOT EXISTS direction VARCHAR(16) NOT NULL DEFAULT 'forward';

        ALTER TABLE acc_map_sales
            DROP CONSTRAINT IF EXISTS chk_acc_map_direction;
        ALTER TABLE acc_map_sales
            ADD CONSTRAINT chk_acc_map_direction
            CHECK (direction IN ('forward', 'reversal'));

        -- 2. Copy rows from acc_map_sales_rev if it exists as a table
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'acc_map_sales_rev') THEN
                INSERT INTO acc_map_sales (tenant_id, mapping_key, account_code, direction, created_at)
                SELECT tenant_id, mapping_key, account_code, 'reversal', created_at
                FROM acc_map_sales_rev
                ON CONFLICT DO NOTHING;

                -- Replace with view
                DROP TABLE acc_map_sales_rev;
                CREATE VIEW acc_map_sales_rev AS
                SELECT id, tenant_id, mapping_key, account_code, created_at
                FROM acc_map_sales WHERE direction = 'reversal';
            ELSIF NOT EXISTS (SELECT 1 FROM pg_views WHERE viewname = 'acc_map_sales_rev') THEN
                CREATE VIEW acc_map_sales_rev AS
                SELECT id, tenant_id, mapping_key, account_code, created_at
                FROM acc_map_sales WHERE direction = 'reversal';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW IF EXISTS acc_map_sales_rev;
        ALTER TABLE acc_map_sales
            DROP CONSTRAINT IF EXISTS chk_acc_map_direction;
        ALTER TABLE acc_map_sales
            DROP COLUMN IF EXISTS direction;
        """
    )

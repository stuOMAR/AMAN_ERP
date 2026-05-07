"""Add B39 operational guard fields and indexes.

Revision: 0025_b39_operational_guards
Revises: 0024_service_pricing_fields
Create Date: 2026-05-02
"""
from alembic import op


revision = "0025_b39_operational_guards"
down_revision = "0024_service_pricing_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE employees
            ADD COLUMN IF NOT EXISTS annual_leave_days INTEGER DEFAULT 30,
            ADD COLUMN IF NOT EXISTS annual_leave_entitlement NUMERIC(8, 2) DEFAULT 30;

        ALTER TABLE pos_orders
            ADD COLUMN IF NOT EXISTS client_order_id VARCHAR(100);

        CREATE UNIQUE INDEX IF NOT EXISTS ux_pos_orders_client_order_id
            ON pos_orders(client_order_id) WHERE client_order_id IS NOT NULL;

        ALTER TABLE opportunity_activities
            ADD COLUMN IF NOT EXISTS contact_id INTEGER REFERENCES crm_contacts(id) ON DELETE SET NULL;

        CREATE INDEX IF NOT EXISTS idx_opportunity_activities_contact_id
            ON opportunity_activities(contact_id);

        CREATE INDEX IF NOT EXISTS idx_journal_entries_created_at
            ON journal_entries(created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_inventory_product_warehouse
            ON inventory(product_id, warehouse_id);

        ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS journal_entries_created_by_fkey;
        ALTER TABLE journal_entries
            ADD CONSTRAINT journal_entries_created_by_fkey
            FOREIGN KEY (created_by) REFERENCES company_users(id) ON DELETE RESTRICT;

        ALTER TABLE pos_orders DROP CONSTRAINT IF EXISTS pos_orders_session_id_fkey;
        ALTER TABLE pos_orders
            ADD CONSTRAINT pos_orders_session_id_fkey
            FOREIGN KEY (session_id) REFERENCES pos_sessions(id) ON DELETE CASCADE;

        ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_parent_id_fkey;
        ALTER TABLE accounts
            ADD CONSTRAINT accounts_parent_id_fkey
            FOREIGN KEY (parent_id) REFERENCES accounts(id) ON DELETE RESTRICT;

        ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_product_id_fkey;
        ALTER TABLE inventory
            ADD CONSTRAINT inventory_product_id_fkey
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_inventory_product_warehouse;
        DROP INDEX IF EXISTS idx_journal_entries_created_at;
        DROP INDEX IF EXISTS idx_opportunity_activities_contact_id;

        ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_product_id_fkey;
        ALTER TABLE inventory
            ADD CONSTRAINT inventory_product_id_fkey
            FOREIGN KEY (product_id) REFERENCES products(id);

        ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_parent_id_fkey;
        ALTER TABLE accounts
            ADD CONSTRAINT accounts_parent_id_fkey
            FOREIGN KEY (parent_id) REFERENCES accounts(id);

        ALTER TABLE pos_orders DROP CONSTRAINT IF EXISTS pos_orders_session_id_fkey;
        ALTER TABLE pos_orders
            ADD CONSTRAINT pos_orders_session_id_fkey
            FOREIGN KEY (session_id) REFERENCES pos_sessions(id);

        ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS journal_entries_created_by_fkey;
        ALTER TABLE journal_entries
            ADD CONSTRAINT journal_entries_created_by_fkey
            FOREIGN KEY (created_by) REFERENCES company_users(id);

        ALTER TABLE opportunity_activities
            DROP COLUMN IF EXISTS contact_id;

        DROP INDEX IF EXISTS ux_pos_orders_client_order_id;

        ALTER TABLE pos_orders
            DROP COLUMN IF EXISTS client_order_id;

        ALTER TABLE employees
            DROP COLUMN IF EXISTS annual_leave_entitlement,
            DROP COLUMN IF EXISTS annual_leave_days;
        """
    )

"""023b: Sales order → invoice link + responsible user.

Revision: 023b_sales_order_invoice_link
Revises: 023a_invoice_state_and_idempotency
Create Date: 2026-05-02

Adds sales_orders.converted_to_invoice_id and responsible_user_id.
"""
from alembic import op
import sqlalchemy as sa


revision = "023b_sales_order_invoice_link"
down_revision = "023a_invoice_state_and_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("sales_orders")]

    op.execute(
        """
        ALTER TABLE sales_orders
            ADD COLUMN IF NOT EXISTS converted_to_invoice_id BIGINT,
            ADD COLUMN IF NOT EXISTS responsible_user_id BIGINT;
        """
    )

    if "tenant_id" in columns:
        op.execute(
            """
            -- Partial unique: each invoice can only be linked from one order
            CREATE UNIQUE INDEX IF NOT EXISTS uix_so_converted_invoice
                ON sales_orders (tenant_id, converted_to_invoice_id)
                WHERE converted_to_invoice_id IS NOT NULL;
            """
        )
    else:
        op.execute(
            """
            -- Partial unique: each invoice can only be linked from one order
            CREATE UNIQUE INDEX IF NOT EXISTS uix_so_converted_invoice
                ON sales_orders (converted_to_invoice_id)
                WHERE converted_to_invoice_id IS NOT NULL;
            """
        )

    op.execute(
        """
        -- FK to invoices
        DO $$ BEGIN
            ALTER TABLE sales_orders
                ADD CONSTRAINT fk_so_converted_invoice
                FOREIGN KEY (converted_to_invoice_id) REFERENCES invoices(id);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;

        -- FK to users
        DO $$ BEGIN
            ALTER TABLE sales_orders
                ADD CONSTRAINT fk_so_responsible_user
                FOREIGN KEY (responsible_user_id) REFERENCES company_users(id);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE sales_orders
            DROP CONSTRAINT IF EXISTS fk_so_responsible_user,
            DROP CONSTRAINT IF EXISTS fk_so_converted_invoice;
        DROP INDEX IF EXISTS uix_so_converted_invoice;
        ALTER TABLE sales_orders
            DROP COLUMN IF EXISTS responsible_user_id,
            DROP COLUMN IF EXISTS converted_to_invoice_id;
        """
    )

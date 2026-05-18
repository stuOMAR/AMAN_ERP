"""029b: tighten invoice idempotency uniqueness.

Revision ID: 029b_invoice_idempotency_unique_key
Revises: 029a_warehouse_gl_inventory_account
Create Date: 2026-05-18

The previous invoice idempotency index included sales_order_id. PostgreSQL
allows multiple NULL values in unique indexes, so direct invoices without a
sales_order_id could still be duplicated under concurrent retries.
"""
from __future__ import annotations

from alembic import op


revision = "029b_invoice_idempotency_unique_key"
down_revision = "029a_warehouse_gl_inventory_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE invoices
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64);

        DROP INDEX IF EXISTS uix_invoice_idempotency;
        CREATE UNIQUE INDEX IF NOT EXISTS uix_invoice_idempotency
            ON invoices (idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS uix_invoice_idempotency;
        CREATE UNIQUE INDEX IF NOT EXISTS uix_invoice_idempotency
            ON invoices (idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        """
    )

"""029a: Per-warehouse inventory GL account.

Revision ID: 029a_warehouse_gl_inventory_account
Revises: 028a_purchase_integrity
Create Date: 2026-05-18

Adds ``warehouses.gl_inventory_account_id`` so each warehouse can be mapped
to a dedicated inventory ledger account. This unlocks two related fixes:

  1. **F-31** — Stock transfers between warehouses now produce a meaningful
     journal entry (Dr Inventory-Destination / Cr Inventory-Source) instead
     of debit + credit on the same global ``acc_map_inventory`` account.
  2. **F-30** — Cross-currency transfers can be posted in base currency
     against per-warehouse accounts, with the transaction-side currency
     captured via ``amount_currency`` on the journal lines.

When a warehouse leaves the column NULL, callers fall back to the legacy
global ``acc_map_inventory`` mapping, so the change is backward compatible.
The migration backfills NULL values to that same global account so existing
data carries on producing the same trial-balance figures it did before.
"""
from __future__ import annotations

from alembic import op


revision = "029a_warehouse_gl_inventory_account"
down_revision = "028a_purchase_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add column (nullable + FK to accounts).
    op.execute(
        """
        ALTER TABLE warehouses
        ADD COLUMN IF NOT EXISTS gl_inventory_account_id INTEGER
        REFERENCES accounts(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_warehouses_gl_inventory_account
        ON warehouses(gl_inventory_account_id)
        """
    )

    # 2. Backfill from acc_map_inventory so the existing trial balance
    #    keeps reconciling after the deploy. We cast the company_settings
    #    value to int because that table stores values as TEXT.
    op.execute(
        """
        UPDATE warehouses w
        SET gl_inventory_account_id = (
            SELECT NULLIF(s.setting_value, '')::int
            FROM company_settings s
            WHERE s.setting_key = 'acc_map_inventory'
            LIMIT 1
        )
        WHERE w.gl_inventory_account_id IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_warehouses_gl_inventory_account")
    op.execute(
        "ALTER TABLE warehouses DROP COLUMN IF EXISTS gl_inventory_account_id"
    )

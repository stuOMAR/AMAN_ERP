"""stock_adjustments + stock_transfer_log: add idempotency_key columns

Revision ID: 030b_stock_idempotency_keys
Revises: 030a_inventory_damaged_qty
Create Date: 2026-05-20

INV-15: stock_adjustments.idempotency_key — prevents duplicate adjustments
        on double-submit or network retry.
INV-16: stock_transfer_log.idempotency_key — prevents duplicate transfer
        documents on network retry (GL already has its own idempotency key).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "030b_stock_idempotency_keys"
down_revision: Union[str, None] = "030a_inventory_damaged_qty"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE stock_adjustments
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_adjustments_idempotency_key
        ON stock_adjustments (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)

    op.execute("""
        ALTER TABLE stock_transfer_log
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_transfer_log_idempotency_key
        ON stock_transfer_log (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_stock_adjustments_idempotency_key")
    op.execute("ALTER TABLE stock_adjustments DROP COLUMN IF EXISTS idempotency_key")
    op.execute("DROP INDEX IF EXISTS uq_stock_transfer_log_idempotency_key")
    op.execute("ALTER TABLE stock_transfer_log DROP COLUMN IF EXISTS idempotency_key")

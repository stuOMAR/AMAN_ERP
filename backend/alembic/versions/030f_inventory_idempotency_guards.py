"""inventory idempotency guards for stock-changing workflows

Revision ID: 030f_inventory_idempotency_guards
Revises: 030e_procurement_idempotency_guards
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op


revision: str = "030f_inventory_idempotency_guards"
down_revision: Union[str, None] = "030e_procurement_idempotency_guards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE stock_shipments
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_shipments_idempotency_key
        ON stock_shipments (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)

    op.execute("""
        ALTER TABLE product_batches
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_product_batches_idempotency_key
        ON product_batches (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)

    op.execute("""
        ALTER TABLE cycle_counts
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_cycle_counts_idempotency_key
        ON cycle_counts (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_cycle_counts_idempotency_key")
    op.execute("ALTER TABLE cycle_counts DROP COLUMN IF EXISTS idempotency_key")
    op.execute("DROP INDEX IF EXISTS uq_product_batches_idempotency_key")
    op.execute("ALTER TABLE product_batches DROP COLUMN IF EXISTS idempotency_key")
    op.execute("DROP INDEX IF EXISTS uq_stock_shipments_idempotency_key")
    op.execute("ALTER TABLE stock_shipments DROP COLUMN IF EXISTS idempotency_key")

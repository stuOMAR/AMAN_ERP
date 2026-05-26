"""pos_orders: add idempotency_key column and unique index

Revision ID: 030j_pos_orders_idempotency
Revises: 030i_sales_quotations_returns_idempotency
Create Date: 2026-05-23

Prevents duplicate POS orders on double-submit or network retry.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "030j_pos_orders_idempotency"
down_revision: Union[str, None] = "030i_sales_quotations_returns_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE pos_orders
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pos_orders_idempotency_key
        ON pos_orders (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_pos_orders_idempotency_key")
    op.execute("ALTER TABLE pos_orders DROP COLUMN IF EXISTS idempotency_key")

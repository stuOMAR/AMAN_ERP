"""sales_orders: add unique index on idempotency_key

Revision ID: 030h_sales_orders_idempotency_key
Revises: 0035_merge_heads
Create Date: 2026-05-23

The idempotency_key column already exists on sales_orders (baseline).
This migration adds the partial unique index so duplicate key inserts are rejected.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "030h_sales_orders_idempotency_key"
down_revision: Union[str, None] = "0035_merge_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_orders_idempotency_key
        ON sales_orders (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_sales_orders_idempotency_key")

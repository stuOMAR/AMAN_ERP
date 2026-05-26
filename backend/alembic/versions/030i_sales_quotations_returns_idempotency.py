"""sales_quotations & sales_returns: add unique idempotency indexes

Revision ID: 030i_sales_quotations_returns_idempotency
Revises: 030h_sales_orders_idempotency_key
Create Date: 2026-05-23

Both tables already have idempotency_key columns but were missing
the partial unique index that enforces uniqueness at the DB level.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "030i_sales_quotations_returns_idempotency"
down_revision: Union[str, None] = "030h_sales_orders_idempotency_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_quotations_idempotency_key
        ON sales_quotations (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_returns_idempotency_key
        ON sales_returns (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_sales_quotations_idempotency_key")
    op.execute("DROP INDEX IF EXISTS uq_sales_returns_idempotency_key")

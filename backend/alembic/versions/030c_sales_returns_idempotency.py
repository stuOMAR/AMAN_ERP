"""sales_returns: add idempotency_key column

Revision ID: 030c_sales_returns_idempotency
Revises: 030b_stock_idempotency_keys
Create Date: 2026-05-20

Fix 10: prevents duplicate sales returns on double-submit or network retry.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "030c_sales_returns_idempotency"
down_revision: Union[str, None] = "030b_stock_idempotency_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE sales_returns
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_returns_idempotency_key
        ON sales_returns (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_sales_returns_idempotency_key")
    op.execute("ALTER TABLE sales_returns DROP COLUMN IF EXISTS idempotency_key")

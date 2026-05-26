"""bill_of_materials: add idempotency_key column

Revision ID: 030k_bom_idempotency
Revises: 030j_pos_orders_idempotency
Create Date: 2026-05-23

Prevents duplicate BOMs on double-submit or network retry.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "030k_bom_idempotency"
down_revision: Union[str, None] = "030j_pos_orders_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE bill_of_materials
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_bill_of_materials_idempotency_key
        ON bill_of_materials (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_bill_of_materials_idempotency_key")
    op.execute("ALTER TABLE bill_of_materials DROP COLUMN IF EXISTS idempotency_key")

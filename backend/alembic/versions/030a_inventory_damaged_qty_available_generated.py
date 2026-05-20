"""inventory: add damaged_quantity, make available_quantity a generated column

Revision ID: 030a_inventory_damaged_qty
Revises: afa5d0a73bb9
Create Date: 2026-05-20

INV-06: adds damaged_quantity column so quarantined/damaged stock is
        excluded from the available formula.
INV-05: converts available_quantity from a plain DEFAULT 0 column (which
        was never maintained) to a GENERATED ALWAYS AS STORED expression
        so it is always correct without any application-level updates.

Formula: available = GREATEST(quantity - reserved_quantity - damaged_quantity, 0)
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "030a_inventory_damaged_qty"
down_revision: Union[str, None] = "afa5d0a73bb9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add damaged_quantity column (safe to add with DEFAULT 0)
    op.execute("""
        ALTER TABLE inventory
        ADD COLUMN IF NOT EXISTS damaged_quantity DECIMAL(18, 4) NOT NULL DEFAULT 0
    """)

    # 2. Drop the old plain available_quantity column (was always 0 — never maintained)
    op.execute("""
        ALTER TABLE inventory
        DROP COLUMN IF EXISTS available_quantity
    """)

    # 3. Re-add as a GENERATED ALWAYS AS STORED computed column
    op.execute("""
        ALTER TABLE inventory
        ADD COLUMN available_quantity DECIMAL(18, 4)
            GENERATED ALWAYS AS (
                GREATEST(
                    quantity
                    - COALESCE(reserved_quantity, 0)
                    - COALESCE(damaged_quantity, 0),
                    0
                )
            ) STORED
    """)


def downgrade() -> None:
    # Revert to plain column with DEFAULT 0 (data loss of generated values is acceptable on downgrade)
    op.execute("ALTER TABLE inventory DROP COLUMN IF EXISTS available_quantity")
    op.execute("ALTER TABLE inventory DROP COLUMN IF EXISTS damaged_quantity")
    op.execute("ALTER TABLE inventory ADD COLUMN available_quantity DECIMAL(18, 4) DEFAULT 0")

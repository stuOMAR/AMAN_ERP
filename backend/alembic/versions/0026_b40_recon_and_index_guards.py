"""Add B40 reconciliation and reporting indexes.

Revision: 0026_b40_recon_and_index_guards
Revises: 0025_b39_operational_guards
Create Date: 2026-05-02
"""
from alembic import op


revision = "0026_b40_recon_and_index_guards"
down_revision = "0025_b39_operational_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_inventory_transactions_product_date
            ON inventory_transactions(product_id, transaction_date);

        CREATE INDEX IF NOT EXISTS idx_payment_vouchers_party_type_id
            ON payment_vouchers(party_type, party_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_payment_vouchers_party_type_id;
        DROP INDEX IF EXISTS idx_inventory_transactions_product_date;
        """
    )

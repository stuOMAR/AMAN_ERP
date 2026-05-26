"""contracts: backend-authoritative billing guards

Revision ID: 031d_contracts_backend_authority
Revises: 031c_crm_opportunities_idempotency
Create Date: 2026-05-25
"""

from typing import Union

from alembic import op


revision: str = "031d_contracts_backend_authority"
down_revision: Union[str, None] = "031c_crm_opportunities_idempotency"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE contracts
        ADD COLUMN IF NOT EXISTS renewal_idempotency_key VARCHAR(64)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_contracts_renewal_idempotency_key
        ON contracts (renewal_idempotency_key)
        WHERE renewal_idempotency_key IS NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE invoices
        ADD COLUMN IF NOT EXISTS contract_id INTEGER REFERENCES contracts(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_invoices_contract
        ON invoices (contract_id)
        """
    )
    op.execute(
        """
        ALTER TABLE contract_milestones
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_contract_milestones_idempotency_key
        ON contract_milestones (idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_contract_milestones_idempotency_key")
    op.execute("ALTER TABLE contract_milestones DROP COLUMN IF EXISTS idempotency_key")
    op.execute("DROP INDEX IF EXISTS idx_invoices_contract")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS contract_id")
    op.execute("DROP INDEX IF EXISTS uq_contracts_renewal_idempotency_key")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS renewal_idempotency_key")

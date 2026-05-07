"""025h: Add party foreign-currency balance column.

Revision: 025h_party_balance_currency
Revises: 025g_accounting_roles
Create Date: 2026-05-04
"""
from alembic import op


revision = "025h_party_balance_currency"
down_revision = "025g_accounting_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.parties') IS NOT NULL THEN
                ALTER TABLE parties
                    ADD COLUMN IF NOT EXISTS balance_currency DECIMAL(18, 4) DEFAULT 0;

                UPDATE parties
                   SET balance_currency = 0
                 WHERE balance_currency IS NULL;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.parties') IS NOT NULL THEN
                ALTER TABLE parties DROP COLUMN IF EXISTS balance_currency;
            END IF;
        END $$;
        """
    )
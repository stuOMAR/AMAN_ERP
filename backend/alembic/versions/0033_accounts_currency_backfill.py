"""Backfill accounts.currency NULL values to base currency.

Revision ID: 0033_accounts_currency_backfill
Revises: 0032_finance_treasury_tax_audit_fixes
Create Date: 2026-05-20
"""
from alembic import op

revision = "0033_accounts_currency_backfill"
down_revision = "0032_finance_treasury_tax_audit_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backfill NULL currency on accounts to the company base currency
    op.execute("""
        UPDATE accounts
        SET currency = (
            SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1
        )
        WHERE currency IS NULL
    """)

    # Add partial unique index on treasury_accounts.gl_account_id for active accounts
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_treasury_accounts_gl_account_active
        ON treasury_accounts (gl_account_id)
        WHERE is_active = TRUE AND gl_account_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_treasury_accounts_gl_account_active")
    # Cannot reverse the NULL backfill safely

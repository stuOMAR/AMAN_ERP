"""treasury audit integration fixes

Revision ID: 030d_treasury_audit_integration_fixes
Revises: 030c_sales_returns_idempotency
Create Date: 2026-05-20
"""
from typing import Sequence, Union
from alembic import op


revision: str = "030d_treasury_audit_integration_fixes"
down_revision: Union[str, None] = "030c_sales_returns_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE treasury_transactions ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(18,6) DEFAULT 1")
    op.execute("ALTER TABLE treasury_transactions ADD COLUMN IF NOT EXISTS currency VARCHAR(10)")
    op.execute("ALTER TABLE treasury_transactions ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120)")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_treasury_transactions_idempotency
        ON treasury_transactions (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)

    op.execute("ALTER TABLE checks_receivable ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(18,6) DEFAULT 1")
    op.execute("ALTER TABLE checks_receivable ADD COLUMN IF NOT EXISTS party_site_id INTEGER REFERENCES party_sites(id)")
    op.execute("ALTER TABLE checks_receivable ADD COLUMN IF NOT EXISTS re_presentation_count INTEGER DEFAULT 0")
    op.execute("ALTER TABLE checks_receivable ADD COLUMN IF NOT EXISTS re_presentation_date DATE")
    op.execute("ALTER TABLE checks_receivable ADD COLUMN IF NOT EXISTS re_presentation_journal_id INTEGER REFERENCES journal_entries(id)")

    op.execute("ALTER TABLE checks_payable ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(18,6) DEFAULT 1")
    op.execute("ALTER TABLE checks_payable ADD COLUMN IF NOT EXISTS party_site_id INTEGER REFERENCES party_sites(id)")
    op.execute("ALTER TABLE checks_payable ADD COLUMN IF NOT EXISTS re_presentation_count INTEGER DEFAULT 0")
    op.execute("ALTER TABLE checks_payable ADD COLUMN IF NOT EXISTS re_presentation_date DATE")
    op.execute("ALTER TABLE checks_payable ADD COLUMN IF NOT EXISTS re_presentation_journal_id INTEGER REFERENCES journal_entries(id)")

    op.execute("ALTER TABLE notes_receivable ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(18,6) DEFAULT 1")
    op.execute("ALTER TABLE notes_receivable ADD COLUMN IF NOT EXISTS party_site_id INTEGER REFERENCES party_sites(id)")
    op.execute("ALTER TABLE notes_payable ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(18,6) DEFAULT 1")
    op.execute("ALTER TABLE notes_payable ADD COLUMN IF NOT EXISTS party_site_id INTEGER REFERENCES party_sites(id)")

    op.execute("ALTER TABLE bank_statements ADD COLUMN IF NOT EXISTS source_file_hash VARCHAR(64)")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_bank_statements_source_file_hash
        ON bank_statements (bank_account_id, source_file_hash)
        WHERE source_file_hash IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_bank_statements_source_file_hash")
    op.execute("ALTER TABLE bank_statements DROP COLUMN IF EXISTS source_file_hash")
    op.execute("ALTER TABLE notes_payable DROP COLUMN IF EXISTS party_site_id")
    op.execute("ALTER TABLE notes_payable DROP COLUMN IF EXISTS exchange_rate")
    op.execute("ALTER TABLE notes_receivable DROP COLUMN IF EXISTS party_site_id")
    op.execute("ALTER TABLE notes_receivable DROP COLUMN IF EXISTS exchange_rate")
    op.execute("ALTER TABLE checks_payable DROP COLUMN IF EXISTS re_presentation_journal_id")
    op.execute("ALTER TABLE checks_payable DROP COLUMN IF EXISTS re_presentation_date")
    op.execute("ALTER TABLE checks_payable DROP COLUMN IF EXISTS re_presentation_count")
    op.execute("ALTER TABLE checks_payable DROP COLUMN IF EXISTS party_site_id")
    op.execute("ALTER TABLE checks_payable DROP COLUMN IF EXISTS exchange_rate")
    op.execute("ALTER TABLE checks_receivable DROP COLUMN IF EXISTS re_presentation_journal_id")
    op.execute("ALTER TABLE checks_receivable DROP COLUMN IF EXISTS re_presentation_date")
    op.execute("ALTER TABLE checks_receivable DROP COLUMN IF EXISTS re_presentation_count")
    op.execute("ALTER TABLE checks_receivable DROP COLUMN IF EXISTS party_site_id")
    op.execute("ALTER TABLE checks_receivable DROP COLUMN IF EXISTS exchange_rate")
    op.execute("ALTER TABLE treasury_transactions DROP COLUMN IF EXISTS currency")
    op.execute("ALTER TABLE treasury_transactions DROP COLUMN IF EXISTS exchange_rate")

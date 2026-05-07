"""025i: Add txn_currency / txn_amount columns to journal_lines and
intercompany_transactions_v2.transaction_currency / transaction_amount.

Solves the tri-currency intercompany scenario (e.g., USD moved between an
SAR branch and an EGP branch): each branch books in its own functional
currency while every line preserves the original transaction currency and
amount for downstream matching, elimination and reporting.

Revision: 025i_journal_lines_txn_currency
Revises: 025h_party_balance_currency
Create Date: 2026-05-06
"""
from alembic import op


revision = "025i_journal_lines_txn_currency"
down_revision = "025h_party_balance_currency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # journal_lines: txn_currency / txn_amount
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.journal_lines') IS NOT NULL THEN
                ALTER TABLE journal_lines
                    ADD COLUMN IF NOT EXISTS txn_currency VARCHAR(10);
                ALTER TABLE journal_lines
                    ADD COLUMN IF NOT EXISTS txn_amount NUMERIC(18, 4);

                -- Backfill from legacy columns
                UPDATE journal_lines
                   SET txn_currency = currency
                 WHERE txn_currency IS NULL AND currency IS NOT NULL;

                UPDATE journal_lines
                   SET txn_amount = amount_currency
                 WHERE txn_amount IS NULL AND amount_currency IS NOT NULL;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_journal_lines_txn_currency
            ON journal_lines (txn_currency)
            WHERE txn_currency IS NOT NULL;
        """
    )

    # intercompany_transactions_v2: original transaction currency / amount
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.intercompany_transactions_v2') IS NOT NULL THEN
                ALTER TABLE intercompany_transactions_v2
                    ADD COLUMN IF NOT EXISTS transaction_currency VARCHAR(10);
                ALTER TABLE intercompany_transactions_v2
                    ADD COLUMN IF NOT EXISTS transaction_amount NUMERIC(18, 4);

                -- Default the new columns to the source-side values for
                -- existing rows (single-currency intercompany prior to
                -- tri-currency support).
                UPDATE intercompany_transactions_v2
                   SET transaction_currency = source_currency
                 WHERE transaction_currency IS NULL;

                UPDATE intercompany_transactions_v2
                   SET transaction_amount = source_amount
                 WHERE transaction_amount IS NULL;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.intercompany_transactions_v2') IS NOT NULL THEN
                ALTER TABLE intercompany_transactions_v2
                    DROP COLUMN IF EXISTS transaction_currency;
                ALTER TABLE intercompany_transactions_v2
                    DROP COLUMN IF EXISTS transaction_amount;
            END IF;
            IF to_regclass('public.journal_lines') IS NOT NULL THEN
                DROP INDEX IF EXISTS idx_journal_lines_txn_currency;
                ALTER TABLE journal_lines
                    DROP COLUMN IF EXISTS txn_amount;
                ALTER TABLE journal_lines
                    DROP COLUMN IF EXISTS txn_currency;
            END IF;
        END $$;
        """
    )

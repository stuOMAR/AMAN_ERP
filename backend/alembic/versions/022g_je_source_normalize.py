"""022g: Normalize journal_entries / invoices source values + CHECK constraints.

Revision: 022g_je_source_normalize
Revises: 022c_account_classifications
Create Date: 2026-05-02

One-pass UPDATE normalises legacy mixed-case ``source`` values to the
lowercase enum set, then adds CHECK constraints so the column stays clean.
"""
from alembic import op


revision = "022g_je_source_normalize"
down_revision = "022c_account_classifications"
branch_labels = None
depends_on = None

_VALID_SOURCES = (
    "sales", "purchase", "payroll", "treasury", "manufacturing",
    "manual", "recurring", "asset", "system",
    "expense", "settlement", "reversal", "intercompany",
    "intercompany_elimination", "subscription", "fx_revaluation",
    "revenue_recognition", "impairment", "ecl_provision", "nrv_test",
    "ifrs15_revenue", "lease", "tax", "provision", "pos",
    "shipment", "delivery", "payment",
)
_SOURCE_EXPR = ", ".join(f"'{s}'" for s in _VALID_SOURCES)


def upgrade() -> None:
    op.execute(
        f"""
        -- 1. Normalize journal_entries.source — lowercase + alias mapping
        UPDATE journal_entries
        SET source = LOWER(TRIM(source))
        WHERE source IS NOT NULL
          AND source != LOWER(TRIM(source));

        -- Map known aliases to canonical values
        UPDATE journal_entries SET source = 'pos' WHERE source IN ('pos-order', 'pos-return');
        UPDATE journal_entries SET source = 'delivery' WHERE source = 'deliveryorder';
        UPDATE journal_entries SET source = 'shipment' WHERE source IN ('shipment_dispatch', 'shipment_receive');
        UPDATE journal_entries SET source = 'treasury' WHERE source IN ('treasury_account_opening', 'treasury_transfer');
        UPDATE journal_entries SET source = 'provision' WHERE source IN ('bad_debt_provision', 'leave_provision');
        UPDATE journal_entries SET source = 'tax' WHERE source IN ('tax_payment', 'tax_settlement');
        UPDATE journal_entries SET source = 'asset' WHERE source = 'asset_transfer';
        UPDATE journal_entries SET source = 'lease' WHERE source IN ('lease_contract', 'lease_payment');
        UPDATE journal_entries SET source = 'impairment' WHERE source = 'impairment_test';

        -- Catch any remaining unknown values → 'system'
        UPDATE journal_entries
        SET source = 'system'
        WHERE source IS NOT NULL
          AND source NOT IN ({_SOURCE_EXPR});

        -- 2. Normalize invoices.source (if the column exists)
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'invoices' AND column_name = 'source'
            ) THEN
                UPDATE invoices SET source = LOWER(TRIM(source))
                WHERE source IS NOT NULL AND source != LOWER(TRIM(source));
                UPDATE invoices SET source = 'pos' WHERE source IN ('pos-order', 'pos-return');
                UPDATE invoices SET source = 'delivery' WHERE source = 'deliveryorder';
                UPDATE invoices SET source = 'system'
                WHERE source IS NOT NULL
                  AND source NOT IN ('sales','purchase','payroll','treasury','manufacturing',
                    'manual','recurring','asset','system','expense','settlement','reversal',
                    'intercompany','intercompany_elimination','subscription','fx_revaluation',
                    'revenue_recognition','impairment','ecl_provision','nrv_test',
                    'ifrs15_revenue','lease','tax','provision','pos','shipment','delivery','payment');
            END IF;
        END $$;

        -- 3. CHECK constraint on journal_entries.source
        ALTER TABLE journal_entries
            DROP CONSTRAINT IF EXISTS ck_je_source_valid;

        ALTER TABLE journal_entries
            ADD CONSTRAINT ck_je_source_valid
            CHECK (source IS NULL OR source IN ({_SOURCE_EXPR}));

        -- 4. CHECK constraint on invoices.source (if column exists)
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'invoices' AND column_name = 'source'
            ) THEN
                ALTER TABLE invoices
                    DROP CONSTRAINT IF EXISTS ck_invoice_source_valid;

                ALTER TABLE invoices
                    ADD CONSTRAINT ck_invoice_source_valid
                    CHECK (source IS NULL OR source IN ({_SOURCE_EXPR}));
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE journal_entries
            DROP CONSTRAINT IF EXISTS ck_je_source_valid;

        ALTER TABLE invoices
            DROP CONSTRAINT IF EXISTS ck_invoice_source_valid;
        """
    )

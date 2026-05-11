"""025k: Harden tax compliance branch, idempotency, and trace fields.

Revision: 025k_tax_compliance_hardening
Revises: 025j_customer_price_lists_branch
Create Date: 2026-05-08
"""
from alembic import op


revision = "025k_tax_compliance_hardening"
down_revision = "025j_customer_price_lists_branch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tax_returns
            ADD COLUMN IF NOT EXISTS currency VARCHAR(3),
            ADD COLUMN IF NOT EXISTS base_currency VARCHAR(3),
            ADD COLUMN IF NOT EXISTS display_currency VARCHAR(3),
            ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(18,6) DEFAULT 1,
            ADD COLUMN IF NOT EXISTS calculation_version VARCHAR(40),
            ADD COLUMN IF NOT EXISTS calculation_details JSONB DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120),
            ADD COLUMN IF NOT EXISTS journal_entry_id INTEGER REFERENCES journal_entries(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_tax_returns_idempotency
            ON tax_returns (idempotency_key) WHERE idempotency_key IS NOT NULL;

        ALTER TABLE tax_payments
            ADD COLUMN IF NOT EXISTS branch_id INTEGER REFERENCES branches(id),
            ADD COLUMN IF NOT EXISTS treasury_account_id INTEGER REFERENCES treasury_accounts(id),
            ADD COLUMN IF NOT EXISTS currency VARCHAR(3),
            ADD COLUMN IF NOT EXISTS base_currency VARCHAR(3),
            ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(18,6) DEFAULT 1,
            ADD COLUMN IF NOT EXISTS journal_entry_id INTEGER REFERENCES journal_entries(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120),
            ADD COLUMN IF NOT EXISTS calculation_version VARCHAR(40),
            ADD COLUMN IF NOT EXISTS calculation_details JSONB DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;
        UPDATE tax_payments tp
           SET branch_id = tr.branch_id
          FROM tax_returns tr
         WHERE tp.tax_return_id = tr.id
           AND tp.branch_id IS NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_tax_payments_idempotency
            ON tax_payments (idempotency_key) WHERE idempotency_key IS NOT NULL;

        ALTER TABLE wht_rates
            ADD COLUMN IF NOT EXISTS country_code VARCHAR(5);
        UPDATE wht_rates SET country_code = COALESCE(country_code, 'SA');

        ALTER TABLE wht_transactions
            ADD COLUMN IF NOT EXISTS branch_id INTEGER REFERENCES branches(id),
            ADD COLUMN IF NOT EXISTS currency VARCHAR(3),
            ADD COLUMN IF NOT EXISTS base_currency VARCHAR(3),
            ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(18,6) DEFAULT 1,
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120),
            ADD COLUMN IF NOT EXISTS calculation_version VARCHAR(40),
            ADD COLUMN IF NOT EXISTS calculation_details JSONB DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
        CREATE UNIQUE INDEX IF NOT EXISTS uq_wht_transactions_idempotency
            ON wht_transactions (idempotency_key) WHERE idempotency_key IS NOT NULL;

        ALTER TABLE tax_calendar
            ADD COLUMN IF NOT EXISTS branch_id INTEGER REFERENCES branches(id),
            ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

        ALTER TABLE zakat_calculations
            ADD COLUMN IF NOT EXISTS branch_id INTEGER REFERENCES branches(id),
            ADD COLUMN IF NOT EXISTS calculation_details JSONB DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS calculation_version VARCHAR(40),
            ADD COLUMN IF NOT EXISTS currency VARCHAR(3),
            ADD COLUMN IF NOT EXISTS base_currency VARCHAR(3),
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120),
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;
        ALTER TABLE zakat_calculations
            ALTER COLUMN zakat_rate SET DEFAULT 0;
        ALTER TABLE zakat_calculations
            DROP CONSTRAINT IF EXISTS zakat_calculations_fiscal_year_key;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_zakat_calculations_year_branch
            ON zakat_calculations (fiscal_year, COALESCE(branch_id, 0));
        CREATE UNIQUE INDEX IF NOT EXISTS uq_zakat_calculations_idempotency
            ON zakat_calculations (idempotency_key) WHERE idempotency_key IS NOT NULL;

        INSERT INTO company_settings (setting_key, setting_value)
        VALUES ('tax.zakat.gregorian_rate', '2.57764')
        ON CONFLICT (setting_key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS uq_zakat_calculations_idempotency;
        DROP INDEX IF EXISTS uq_zakat_calculations_year_branch;
        DROP INDEX IF EXISTS uq_wht_transactions_idempotency;
        DROP INDEX IF EXISTS uq_tax_payments_idempotency;
        DROP INDEX IF EXISTS uq_tax_returns_idempotency;

        ALTER TABLE zakat_calculations
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS idempotency_key,
            DROP COLUMN IF EXISTS base_currency,
            DROP COLUMN IF EXISTS currency,
            DROP COLUMN IF EXISTS calculation_version,
            DROP COLUMN IF EXISTS calculation_details,
            DROP COLUMN IF EXISTS branch_id;
        ALTER TABLE tax_calendar
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS completed_at,
            DROP COLUMN IF EXISTS is_active,
            DROP COLUMN IF EXISTS branch_id;
        ALTER TABLE wht_transactions
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS calculation_details,
            DROP COLUMN IF EXISTS calculation_version,
            DROP COLUMN IF EXISTS idempotency_key,
            DROP COLUMN IF EXISTS exchange_rate,
            DROP COLUMN IF EXISTS base_currency,
            DROP COLUMN IF EXISTS currency,
            DROP COLUMN IF EXISTS branch_id;
        ALTER TABLE wht_rates DROP COLUMN IF EXISTS country_code;
        ALTER TABLE tax_payments
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS calculation_details,
            DROP COLUMN IF EXISTS calculation_version,
            DROP COLUMN IF EXISTS idempotency_key,
            DROP COLUMN IF EXISTS journal_entry_id,
            DROP COLUMN IF EXISTS exchange_rate,
            DROP COLUMN IF EXISTS base_currency,
            DROP COLUMN IF EXISTS currency,
            DROP COLUMN IF EXISTS treasury_account_id,
            DROP COLUMN IF EXISTS branch_id;
        ALTER TABLE tax_returns
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS journal_entry_id,
            DROP COLUMN IF EXISTS idempotency_key,
            DROP COLUMN IF EXISTS calculation_details,
            DROP COLUMN IF EXISTS calculation_version,
            DROP COLUMN IF EXISTS exchange_rate,
            DROP COLUMN IF EXISTS display_currency,
            DROP COLUMN IF EXISTS base_currency,
            DROP COLUMN IF EXISTS currency;
        """
    )

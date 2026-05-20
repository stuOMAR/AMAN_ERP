"""Finance/treasury/tax audit schema fixes.

Revision ID: 0032_finance_treasury_tax_audit_fixes
Revises: 0031_bank_statement_match_unique
Create Date: 2026-05-20
"""
from alembic import op


revision = "0032_finance_treasury_tax_audit_fixes"
down_revision = "0031_bank_statement_match_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE invoices
            ADD COLUMN IF NOT EXISTS zatca_clearance_status VARCHAR(30) NOT NULL DEFAULT 'not_required',
            ADD COLUMN IF NOT EXISTS zatca_cleared_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS zatca_cleared_uuid VARCHAR(80),
            ADD COLUMN IF NOT EXISTS zatca_clearance_error TEXT;

        CREATE INDEX IF NOT EXISTS ix_invoices_zatca_clearance_status
            ON invoices (zatca_clearance_status)
            WHERE zatca_clearance_status IN ('pending_clearance','rejected');

        WITH grouped AS (
            SELECT period_start, period_end,
                   BOOL_OR(is_locked) AS any_locked,
                   MAX(locked_at) AS latest_locked_at
            FROM fiscal_period_locks
            GROUP BY period_start, period_end
            HAVING COUNT(*) > 1
        )
        UPDATE fiscal_period_locks f
           SET is_locked = g.any_locked,
               locked_at = COALESCE(g.latest_locked_at, f.locked_at)
          FROM grouped g
         WHERE f.id = (
            SELECT kept.id
            FROM fiscal_period_locks kept
            WHERE kept.period_start = g.period_start
              AND kept.period_end = g.period_end
            ORDER BY kept.locked_at DESC NULLS LAST,
                     kept.created_at DESC NULLS LAST,
                     kept.id DESC
            LIMIT 1
         );

        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY period_start, period_end
                       ORDER BY locked_at DESC NULLS LAST,
                                created_at DESC NULLS LAST,
                                id DESC
                   ) AS rn
            FROM fiscal_period_locks
        )
        DELETE FROM fiscal_period_locks f
        USING ranked r
        WHERE f.id = r.id AND r.rn > 1;

        CREATE UNIQUE INDEX IF NOT EXISTS uq_fiscal_period_locks_period
            ON fiscal_period_locks (period_start, period_end);

        ALTER TABLE zatca_outbox
            ADD COLUMN IF NOT EXISTS max_attempts INT NOT NULL DEFAULT 5;

        ALTER TABLE einvoice_outbox
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_einvoice_outbox_idempotency
            ON einvoice_outbox (idempotency_key) WHERE idempotency_key IS NOT NULL;

        ALTER TABLE entity_groups
            ADD COLUMN IF NOT EXISTS branch_id INTEGER REFERENCES branches(id);
        CREATE INDEX IF NOT EXISTS ix_entity_groups_branch_id
            ON entity_groups (branch_id) WHERE is_deleted = false;

        ALTER TABLE intercompany_transactions_v2
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_intercompany_transactions_v2_idempotency
            ON intercompany_transactions_v2 (idempotency_key)
            WHERE idempotency_key IS NOT NULL;

        CREATE OR REPLACE FUNCTION assert_period_open() RETURNS trigger AS $fn_period$
        DECLARE
            v_closed BOOLEAN;
            v_locked BOOLEAN;
        BEGIN
            IF NEW.status IS DISTINCT FROM 'posted' THEN
                RETURN NEW;
            END IF;

            SELECT TRUE INTO v_closed
            FROM fiscal_periods
            WHERE NEW.entry_date BETWEEN start_date AND end_date
              AND is_closed = TRUE
            LIMIT 1;
            IF v_closed THEN
                RAISE EXCEPTION 'Posting into a closed fiscal period is forbidden (entry_date=%)', NEW.entry_date
                    USING ERRCODE = '23514';
            END IF;

            SELECT TRUE INTO v_locked
            FROM fiscal_period_locks
            WHERE NEW.entry_date BETWEEN period_start AND period_end
              AND is_locked = TRUE
            LIMIT 1;
            IF v_locked THEN
                RAISE EXCEPTION 'Posting into a locked fiscal period is forbidden (entry_date=%)', NEW.entry_date
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $fn_period$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_je_period_open ON journal_entries;
        CREATE TRIGGER trg_je_period_open
            BEFORE INSERT OR UPDATE OF status, entry_date ON journal_entries
            FOR EACH ROW EXECUTE FUNCTION assert_period_open();

        CREATE OR REPLACE FUNCTION assert_journal_line_account_currency()
        RETURNS trigger AS $fn$
        DECLARE
            v_account_currency TEXT;
        BEGIN
            SELECT currency INTO v_account_currency
            FROM accounts
            WHERE id = NEW.account_id;

            IF v_account_currency IS NOT NULL
               AND NEW.currency IS NOT NULL
               AND UPPER(v_account_currency) <> UPPER(NEW.currency) THEN
                RAISE EXCEPTION 'Journal line currency % does not match account currency % for account %',
                    NEW.currency, v_account_currency, NEW.account_id
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $fn$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_journal_line_account_currency ON journal_lines;
        CREATE TRIGGER trg_journal_line_account_currency
            BEFORE INSERT OR UPDATE OF account_id, currency ON journal_lines
            FOR EACH ROW EXECUTE FUNCTION assert_journal_line_account_currency();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS uq_fiscal_period_locks_period;
        DROP INDEX IF EXISTS ix_invoices_zatca_clearance_status;
        DROP INDEX IF EXISTS uq_einvoice_outbox_idempotency;
        DROP INDEX IF EXISTS uq_intercompany_transactions_v2_idempotency;
        DROP INDEX IF EXISTS ix_entity_groups_branch_id;
        DROP TRIGGER IF EXISTS trg_journal_line_account_currency ON journal_lines;
        DROP FUNCTION IF EXISTS assert_journal_line_account_currency();
        ALTER TABLE intercompany_transactions_v2 DROP COLUMN IF EXISTS idempotency_key;
        ALTER TABLE entity_groups DROP COLUMN IF EXISTS branch_id;
        ALTER TABLE einvoice_outbox DROP COLUMN IF EXISTS idempotency_key;
        ALTER TABLE zatca_outbox DROP COLUMN IF EXISTS max_attempts;
        ALTER TABLE invoices
            DROP COLUMN IF EXISTS zatca_clearance_error,
            DROP COLUMN IF EXISTS zatca_cleared_uuid,
            DROP COLUMN IF EXISTS zatca_cleared_at,
            DROP COLUMN IF EXISTS zatca_clearance_status;
        """
    )

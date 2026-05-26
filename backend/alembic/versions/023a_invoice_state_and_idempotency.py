"""023a: Invoice state machine + idempotency key.

Revision: 023a_invoice_state_and_idempotency
Revises: 022h_device_fingerprints_login_geo
Create Date: 2026-05-02

Adds invoices.state, idempotency_key, posted_at, posted_by, state_reason.
Backfill state from existing posted/cancelled flags.
"""
from alembic import op


revision = "023a_invoice_state_and_idempotency"
down_revision = "022h_device_fingerprints_login_geo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- 1. Add state column with CHECK constraint
        ALTER TABLE invoices
            ADD COLUMN IF NOT EXISTS state VARCHAR(32) NOT NULL DEFAULT 'draft';

        ALTER TABLE invoices
            DROP CONSTRAINT IF EXISTS chk_invoice_state;
        ALTER TABLE invoices
            ADD CONSTRAINT chk_invoice_state
            CHECK (state IN ('draft','posted','submitted','cleared','reported','reversed','cancelled'));

        -- 2. Backfill state from existing flags
        UPDATE invoices SET state = 'cancelled'
        WHERE status = 'cancelled' AND state = 'draft';
        UPDATE invoices SET state = 'posted'
        WHERE status IN ('paid','completed','sent') AND state = 'draft';

        -- 3. Add idempotency + posting metadata columns
        ALTER TABLE invoices
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64),
            ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS posted_by BIGINT,
            ADD COLUMN IF NOT EXISTS state_reason TEXT;

        -- 4. Partial unique index for idempotency
        DROP INDEX IF EXISTS uix_invoice_idempotency;
        CREATE UNIQUE INDEX IF NOT EXISTS uix_invoice_idempotency
            ON invoices (idempotency_key)
            WHERE idempotency_key IS NOT NULL;

        -- 5. Index on state for queries
        CREATE INDEX IF NOT EXISTS ix_invoices_state
            ON invoices (state);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_invoices_state;
        DROP INDEX IF EXISTS uix_invoice_idempotency;
        ALTER TABLE invoices
            DROP COLUMN IF EXISTS state_reason,
            DROP COLUMN IF EXISTS posted_by,
            DROP COLUMN IF EXISTS posted_at,
            DROP COLUMN IF EXISTS idempotency_key;
        ALTER TABLE invoices
            DROP CONSTRAINT IF EXISTS chk_invoice_state;
        ALTER TABLE invoices
            DROP COLUMN IF EXISTS state;
        """
    )

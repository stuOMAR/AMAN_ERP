"""Audit H batch 10: DDL sync for the High-tier remediation set.

Closes the four R-DDL-* findings F-NEW-019..022 from the
finance/treasury/tax/zatca audit:

* F-NEW-019 (R-DDL-MISSING-COLUMN): adds `treasury_transactions.idempotency_key`
  + a partial-unique index so `/api/treasury/transfers` and the other treasury
  POST endpoints can deduplicate retries. Without the column the upcoming
  Batch 11 idempotency wiring has no place to write the key.
* F-NEW-020 (R-DDL-MISSING-COLUMN): adds `bank_statements.source_hash`
  + a per-bank-account partial unique index so MT940/CSV/CAMT.053 imports
  can refuse duplicate uploads of the same statement file.
* F-NEW-021 (R-DDL-MISSING-COLUMN): adds `zatca_outbox.last_idempotency_key`
  so the outbox reprocess admin endpoint can record the latest replay key
  without losing the original ZATCA submission `idempotency_key`.
* F-NEW-022 (R-DDL-TABLE-MISSING): re-applies the `zatca_csid` create that
  previously lived only on the *separate* `0015_zatca_csid` branch but had
  not been declared in the production tenant schema source-of-truth. The
  migration uses `CREATE TABLE IF NOT EXISTS` so re-running on databases
  already migrated through the 0015 branch is a no-op.

Idempotent: every statement uses `IF NOT EXISTS`. Safe to run on tenants
freshly provisioned from `tenant_schema.py` (which Batch 10 also patches)
or on tenants that pre-date this remediation cycle.
"""
from alembic import op


revision = "0030_audit_h_ddl_sync"
down_revision = "029b_invoice_idempotency_unique_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- ───────────────────────────────────────────────────────────────
        -- F-NEW-019: treasury_transactions.idempotency_key
        -- ───────────────────────────────────────────────────────────────
        ALTER TABLE treasury_transactions
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_treasury_transactions_idempotency
            ON treasury_transactions (idempotency_key)
            WHERE idempotency_key IS NOT NULL;

        -- ───────────────────────────────────────────────────────────────
        -- F-NEW-020: bank_statements.source_hash
        -- A SHA-256 (hex) of the raw uploaded payload. Same content on
        -- the SAME bank_account_id is rejected; uploading the same content
        -- to a different account is still allowed because two banks may
        -- legitimately produce identical lines for the same period.
        -- ───────────────────────────────────────────────────────────────
        ALTER TABLE bank_statements
            ADD COLUMN IF NOT EXISTS source_hash VARCHAR(64);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_bank_statements_source_hash
            ON bank_statements (bank_account_id, source_hash)
            WHERE source_hash IS NOT NULL;

        -- ───────────────────────────────────────────────────────────────
        -- F-NEW-021: zatca_outbox.last_idempotency_key
        -- The 64-char column matches the existing `idempotency_key` width
        -- on the same table.
        -- ───────────────────────────────────────────────────────────────
        ALTER TABLE zatca_outbox
            ADD COLUMN IF NOT EXISTS last_idempotency_key VARCHAR(64);
        CREATE INDEX IF NOT EXISTS ix_zatca_outbox_last_idempotency
            ON zatca_outbox (tenant_id, last_idempotency_key)
            WHERE last_idempotency_key IS NOT NULL;

        -- ───────────────────────────────────────────────────────────────
        -- F-NEW-022: zatca_csid table (re-apply for tenants provisioned
        -- through `tenant_schema.py` rather than through the 0015 branch).
        -- ───────────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS zatca_csid (
            id              SERIAL PRIMARY KEY,
            environment     VARCHAR(20) NOT NULL DEFAULT 'production'
                            CHECK (environment IN ('compliance','production')),
            pcsid           TEXT NOT NULL,
            secret_encrypted TEXT NOT NULL,
            common_name     VARCHAR(200),
            serial_number   VARCHAR(80),
            issued_at       TIMESTAMPTZ NOT NULL,
            expires_at      TIMESTAMPTZ NOT NULL,
            status          VARCHAR(20) NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active','expired','revoked','superseded')),
            last_alert_at   TIMESTAMPTZ,
            last_alert_threshold_days INTEGER,
            renewed_to_id   INTEGER REFERENCES zatca_csid(id) ON DELETE SET NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (expires_at > issued_at)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_zatca_csid_active
            ON zatca_csid (environment) WHERE status = 'active';
        CREATE INDEX IF NOT EXISTS ix_zatca_csid_expiring
            ON zatca_csid (expires_at) WHERE status = 'active';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS uq_treasury_transactions_idempotency;
        ALTER TABLE treasury_transactions DROP COLUMN IF EXISTS idempotency_key;

        DROP INDEX IF EXISTS uq_bank_statements_source_hash;
        ALTER TABLE bank_statements DROP COLUMN IF EXISTS source_hash;

        DROP INDEX IF EXISTS ix_zatca_outbox_last_idempotency;
        ALTER TABLE zatca_outbox DROP COLUMN IF EXISTS last_idempotency_key;

        -- The `zatca_csid` table is left in place on downgrade because it
        -- may already have been provisioned through the 0015 branch on
        -- some tenants; dropping it here would also drop legitimate data
        -- for those tenants. Operators who need to drop it should run the
        -- 0015 downgrade explicitly.
        """
    )

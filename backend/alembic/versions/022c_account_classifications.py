"""022c: Create account_classifications table + seed defaults.

Revision: 022c_account_classifications
Revises: 022b_integration_credentials
Create Date: 2026-05-02

Creates the ``account_classifications`` table that replaces hard-coded
account-code-range checks.  Backfills one active row per existing account
using the legacy code-digit heuristic so day-one report behaviour is
preserved.
"""
from alembic import op


revision = "022c_account_classifications"
down_revision = "022b_integration_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- 1. Table ──────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS account_classifications (
            id                BIGSERIAL     PRIMARY KEY,
            tenant_id         BIGINT        NOT NULL,
            account_id        BIGINT        NOT NULL
                              REFERENCES accounts(id) ON DELETE CASCADE,
            statement_category VARCHAR(32)  NOT NULL,
            sign              SMALLINT      NOT NULL,
            aggregation_hint  VARCHAR(64),
            is_active         BOOLEAN       NOT NULL DEFAULT true,
            valid_from        DATE          NOT NULL,
            valid_to          DATE,
            created_at        TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp(),
            updated_at        TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp()
        );

        -- 2. Partial unique: at most one active row per (tenant, account).
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ac_active
            ON account_classifications (tenant_id, account_id)
            WHERE is_active = true;

        -- 3. Lookup index for report queries.
        CREATE INDEX IF NOT EXISTS ix_ac_tenant_account
            ON account_classifications (tenant_id, account_id)
            WHERE is_active = true;

        -- 4. Seed: backfill one active row per existing account.
        --    Heuristic based on first digit of account_number:
        --      1xxx → asset    +1
        --      2xxx → liability -1
        --      3xxx → equity   +1
        --      4xxx → revenue  -1
        --      5xxx → expense  +1
        INSERT INTO account_classifications
            (tenant_id, account_id, statement_category, sign,
             aggregation_hint, is_active, valid_from)
        SELECT
            current_setting('app.tenant_id', true)::bigint,
            a.id,
            CASE LEFT(a.account_number::text, 1)
                WHEN '1' THEN 'asset'
                WHEN '2' THEN 'liability'
                WHEN '3' THEN 'equity'
                WHEN '4' THEN 'revenue'
                WHEN '5' THEN 'expense'
                ELSE 'asset'           -- fallback for edge cases
            END AS statement_category,
            CASE LEFT(a.account_number::text, 1)
                WHEN '1' THEN  1
                WHEN '2' THEN -1
                WHEN '3' THEN  1
                WHEN '4' THEN -1
                WHEN '5' THEN  1
                ELSE  1
            END AS sign,
            'seed' AS aggregation_hint,
            true  AS is_active,
            CURRENT_DATE AS valid_from
        FROM accounts a
        WHERE a.account_number IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM account_classifications ac
              WHERE ac.account_id = a.id
                AND ac.is_active = true
          );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_ac_tenant_account;
        DROP INDEX IF EXISTS uq_ac_active;
        DROP TABLE IF EXISTS account_classifications;
        """
    )

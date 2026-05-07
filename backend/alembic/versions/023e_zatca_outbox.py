"""023e: ZATCA outbox table.

Revision: 023e_zatca_outbox
Revises: 023d_acc_map_sales_consolidation
Create Date: 2026-05-02
"""
from alembic import op


revision = "023e_zatca_outbox"
down_revision = "023d_acc_map_sales_consolidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS zatca_outbox (
            id                  BIGSERIAL       PRIMARY KEY,
            tenant_id           BIGINT          NOT NULL,
            invoice_id          BIGINT          NOT NULL,
            state               VARCHAR(20)     NOT NULL DEFAULT 'pending',
            attempts            INT             NOT NULL DEFAULT 0,
            next_attempt_at     TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
            last_error          TEXT,
            idempotency_key     VARCHAR(64),
            signed_xml          TEXT,
            cleared_reference   VARCHAR(64),
            reported_reference  VARCHAR(64),
            submitted_at        TIMESTAMPTZ,
            acknowledged_at     TIMESTAMPTZ,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
        );

        ALTER TABLE zatca_outbox
            DROP CONSTRAINT IF EXISTS chk_zatca_outbox_state;
        ALTER TABLE zatca_outbox
            ADD CONSTRAINT chk_zatca_outbox_state
            CHECK (state IN ('pending','submitting','submitted','cleared','reported','failed','dead_letter'));

        -- Unique: one outbox row per invoice
        CREATE UNIQUE INDEX IF NOT EXISTS uix_zatca_outbox_invoice
            ON zatca_outbox (tenant_id, invoice_id);

        -- Worker partial index: pending or failed rows ready for retry
        CREATE INDEX IF NOT EXISTS ix_zatca_outbox_worker
            ON zatca_outbox (tenant_id, state, next_attempt_at)
            WHERE state IN ('pending', 'failed');
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_zatca_outbox_worker;
        DROP INDEX IF EXISTS uix_zatca_outbox_invoice;
        ALTER TABLE zatca_outbox DROP CONSTRAINT IF EXISTS chk_zatca_outbox_state;
        DROP TABLE IF EXISTS zatca_outbox;
        """
    )

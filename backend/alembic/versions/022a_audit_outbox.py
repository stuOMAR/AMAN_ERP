"""022a: Create audit_outbox table + audit_logs.critical flag.

Revision: 022a_audit_outbox
Revises: 0026_b40_recon_and_index_guards
Create Date: 2026-05-02

Creates the transactional outbox buffer for audit rows.  Writes land in
``audit_outbox`` on the caller's session (committed atomically with the
business transaction) and are flushed to ``audit_logs`` by a background
worker.

Also adds ``audit_logs.critical`` and a composite index if missing.
"""
from alembic import op


revision = "022a_audit_outbox"
down_revision = "0026_b40_recon_and_index_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- 1. audit_outbox table
        CREATE TABLE IF NOT EXISTS audit_outbox (
            id            BIGSERIAL    PRIMARY KEY,
            tenant_id     VARCHAR(100) NOT NULL,
            actor_id      BIGINT,
            action        VARCHAR(64)  NOT NULL,
            entity_type   VARCHAR(64),
            entity_id     VARCHAR(100),
            payload       JSONB        NOT NULL DEFAULT '{}',
            critical      BOOLEAN      NOT NULL DEFAULT false,
            enqueued_at   TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),
            flushed_at    TIMESTAMPTZ,
            attempt_count INT          NOT NULL DEFAULT 0,
            last_error    TEXT
        );

        -- 2. Partial index for worker flush (pending rows only).
        CREATE INDEX IF NOT EXISTS ix_audit_outbox_pending
            ON audit_outbox (tenant_id, enqueued_at)
            WHERE flushed_at IS NULL;

        -- 3. audit_logs.critical flag (idempotent).
        ALTER TABLE audit_logs
            ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100),
            ADD COLUMN IF NOT EXISTS critical BOOLEAN NOT NULL DEFAULT false;

        -- 4. Composite index for critical-action queries.
        CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_action_created
            ON audit_logs (tenant_id, action, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX  IF EXISTS ix_audit_logs_tenant_action_created;
        ALTER TABLE audit_logs DROP COLUMN IF EXISTS critical;
        DROP TABLE  IF EXISTS audit_outbox;
        """
    )

"""025a: Repair missing tenant audit_outbox table.

Revision: 025a_audit_outbox_repair
Revises: afa5d0a73bb9
Create Date: 2026-05-02

Some local tenant databases reached the merged head without the 022a
audit outbox DDL. This migration is intentionally idempotent so it can
repair existing tenants without disturbing healthy ones.
"""
from alembic import op


revision = "025a_audit_outbox_repair"
down_revision = "afa5d0a73bb9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_outbox (
            id BIGSERIAL PRIMARY KEY,
            tenant_id VARCHAR(100) NOT NULL,
            actor_id BIGINT,
            action VARCHAR(64) NOT NULL,
            entity_type VARCHAR(64),
            entity_id VARCHAR(100),
            payload JSONB NOT NULL DEFAULT '{}',
            critical BOOLEAN NOT NULL DEFAULT false,
            enqueued_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            flushed_at TIMESTAMPTZ,
            attempt_count INT NOT NULL DEFAULT 0,
            last_error TEXT
        );

        CREATE INDEX IF NOT EXISTS ix_audit_outbox_pending
            ON audit_outbox (tenant_id, enqueued_at)
            WHERE flushed_at IS NULL;

        DO $$
        BEGIN
            IF to_regclass('public.audit_logs') IS NOT NULL THEN
                ALTER TABLE audit_logs
                    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS critical BOOLEAN NOT NULL DEFAULT false;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_audit_outbox_pending;
        DROP TABLE IF EXISTS audit_outbox;
        """
    )
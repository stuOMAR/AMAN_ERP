"""Notifications queue table.

Feature 024 — T012.
"""
from alembic import op

revision = "024p_notifications_queue"
down_revision = "024o_storage_quotas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS notifications_queue (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            idempotency_key CHAR(32),
            event_type VARCHAR(64) NOT NULL,
            channel VARCHAR(16) NOT NULL,
            recipient VARCHAR(512) NOT NULL,
            template_code VARCHAR(64),
            locale CHAR(5),
            payload JSONB,
            state VARCHAR(16) DEFAULT 'pending',
            attempts SMALLINT DEFAULT 0,
            next_attempt_at TIMESTAMPTZ,
            last_error TEXT,
            claimed_at TIMESTAMPTZ,
            sent_at TIMESTAMPTZ,
            dlq_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT clock_timestamp(),
            updated_at TIMESTAMPTZ DEFAULT clock_timestamp()
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_notif_inflight
            ON notifications_queue (tenant_id, idempotency_key)
            WHERE state IN ('pending', 'sending') AND idempotency_key IS NOT NULL;
        CREATE INDEX IF NOT EXISTS ix_notif_worker
            ON notifications_queue (channel, state, next_attempt_at);
        CREATE INDEX IF NOT EXISTS ix_notif_dlq
            ON notifications_queue (state, dlq_at);
    """)


def downgrade() -> None:
    op.drop_table("notifications_queue")

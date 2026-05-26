"""integrations: sync DMS, notification queue, imports, and webhook outbox DDL

Revision ID: 031g_integrations_dms_notifications_imports
Revises: 031f_approvals_workflow_security_authority
"""
from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "031g_integrations_dms_notifications_imports"
down_revision: Union[str, None] = "031f_approvals_workflow_security_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS state VARCHAR(16) DEFAULT 'clean';
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS quarantine_path VARCHAR(1024);
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS scanned_at TIMESTAMPTZ;
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS scan_engine VARCHAR(64);
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS scan_engine_version VARCHAR(64);
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS checksum_sha256 CHAR(64);
        CREATE INDEX IF NOT EXISTS idx_documents_state ON documents(state);

        CREATE TABLE IF NOT EXISTS dms_attachment_links (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            entity_type VARCHAR(64) NOT NULL,
            entity_id BIGINT NOT NULL,
            link_role VARCHAR(64),
            created_by_user_id BIGINT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_att_link_unique
            ON dms_attachment_links (tenant_id, document_id, entity_type, entity_id, COALESCE(link_role, ''));
        CREATE INDEX IF NOT EXISTS ix_att_link_entity
            ON dms_attachment_links(entity_type, entity_id);
        CREATE INDEX IF NOT EXISTS ix_att_link_document
            ON dms_attachment_links(document_id);

        CREATE TABLE IF NOT EXISTS storage_quotas (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            scope VARCHAR(16) NOT NULL,
            scope_ref_id BIGINT DEFAULT 0,
            used_bytes BIGINT DEFAULT 0,
            quota_bytes BIGINT NOT NULL,
            last_recalculated_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
        ALTER TABLE storage_quotas ALTER COLUMN scope_ref_id SET DEFAULT 0;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_storage_quota_scope
            ON storage_quotas(tenant_id, scope, scope_ref_id);

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
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_notif_inflight
            ON notifications_queue(tenant_id, idempotency_key)
            WHERE state IN ('pending', 'sending') AND idempotency_key IS NOT NULL;
        CREATE INDEX IF NOT EXISTS ix_notif_worker
            ON notifications_queue(channel, state, next_attempt_at);
        CREATE INDEX IF NOT EXISTS ix_notif_dlq
            ON notifications_queue(state, dlq_at);

        ALTER TABLE bank_import_batches ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120);
        ALTER TABLE bank_import_batches ADD COLUMN IF NOT EXISTS source_file_hash VARCHAR(64);
        ALTER TABLE bank_import_batches ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_bank_import_batches_idempotency_key
            ON bank_import_batches(idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_bank_import_batches_source_file_hash
            ON bank_import_batches(bank_account_id, source_file_hash)
            WHERE source_file_hash IS NOT NULL;

        ALTER TABLE webhook_logs ADD COLUMN IF NOT EXISTS error_message TEXT;
        CREATE TABLE IF NOT EXISTS webhook_outbox (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL DEFAULT 0,
            webhook_id INT REFERENCES webhooks(id) ON DELETE CASCADE,
            event VARCHAR(100) NOT NULL,
            payload JSONB NOT NULL,
            state VARCHAR(20) NOT NULL DEFAULT 'pending',
            attempts INT NOT NULL DEFAULT 0,
            last_error TEXT,
            next_attempt_at TIMESTAMPTZ DEFAULT NOW(),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_webhook_outbox_worker
            ON webhook_outbox(state, next_attempt_at);
        CREATE INDEX IF NOT EXISTS ix_webhook_outbox_webhook
            ON webhook_outbox(webhook_id, event);
        """
    )


def downgrade() -> None:
    # Repair migration: leave shared integration structures in place.
    pass

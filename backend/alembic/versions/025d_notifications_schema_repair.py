"""025d: Repair notification queue and template admin schema.

Revision: 025d_notifications_schema_repair
Revises: 025c_reports_schema_repair
Create Date: 2026-05-03

Local tenant databases can be stamped at the current feature head while
missing Feature 024 notification tables/columns. This migration creates the
queue table and extends the legacy email_templates table without removing its
older columns.
"""
from alembic import op


revision = "025d_notifications_schema_repair"
down_revision = "025c_reports_schema_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
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
            state VARCHAR(16) NOT NULL DEFAULT 'pending',
            attempts SMALLINT NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ,
            last_error TEXT,
            claimed_at TIMESTAMPTZ,
            sent_at TIMESTAMPTZ,
            dlq_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_notif_inflight
            ON notifications_queue (tenant_id, idempotency_key)
            WHERE state IN ('pending', 'sending') AND idempotency_key IS NOT NULL;
        CREATE INDEX IF NOT EXISTS ix_notif_worker
            ON notifications_queue (channel, state, next_attempt_at);
        CREATE INDEX IF NOT EXISTS ix_notif_dlq
            ON notifications_queue (state, dlq_at);

        CREATE TABLE IF NOT EXISTS email_templates (
            id SERIAL PRIMARY KEY,
            template_name VARCHAR(255),
            subject VARCHAR(255),
            body TEXT,
            variables JSONB DEFAULT '{}',
            is_active BOOLEAN DEFAULT true,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );

        ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS tenant_id BIGINT;
        ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS code VARCHAR(64);
        ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS locale CHAR(5) DEFAULT 'en';
        ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS body_html TEXT;
        ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS body_text TEXT;
        ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS version INT DEFAULT 1;
        ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT clock_timestamp();

        WITH ctx AS (
            SELECT CASE
                WHEN current_database() ~ '^aman_[0-9]+$'
                THEN regexp_replace(current_database(), '^aman_', '')::bigint
                ELSE 0
            END AS tenant_id
        )
        UPDATE email_templates et
           SET tenant_id = COALESCE(et.tenant_id, ctx.tenant_id),
               code = COALESCE(NULLIF(et.code, ''), NULLIF(et.template_name, ''), 'template_' || et.id::text),
               locale = COALESCE(et.locale, 'en'),
               body_html = COALESCE(et.body_html, et.body),
               body_text = COALESCE(et.body_text, et.body),
               version = COALESCE(et.version, 1),
               updated_at = COALESCE(et.updated_at, clock_timestamp())
        FROM ctx
        WHERE et.tenant_id IS NULL
           OR et.code IS NULL
           OR et.locale IS NULL
           OR et.body_html IS NULL
           OR et.body_text IS NULL
           OR et.version IS NULL
           OR et.updated_at IS NULL;

        ALTER TABLE email_templates ALTER COLUMN tenant_id SET NOT NULL;
        ALTER TABLE email_templates ALTER COLUMN code SET NOT NULL;
        ALTER TABLE email_templates ALTER COLUMN locale SET NOT NULL;
        ALTER TABLE email_templates ALTER COLUMN version SET NOT NULL;

        CREATE INDEX IF NOT EXISTS ix_email_templates_tenant_code_locale
            ON email_templates (tenant_id, code, locale);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_email_templates_tenant_code_locale;
        DROP INDEX IF EXISTS ix_notif_dlq;
        DROP INDEX IF EXISTS ix_notif_worker;
        DROP INDEX IF EXISTS uq_notif_inflight;
        DROP TABLE IF EXISTS notifications_queue;
        """
    )
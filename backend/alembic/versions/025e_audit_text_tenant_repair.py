"""025e: Repair audit tenant identifiers for text company codes.

Revision: 025e_audit_text_tenant_repair
Revises: 025d_notifications_schema_repair
Create Date: 2026-05-03

The tenant architecture uses company codes such as ``e24bcd11`` as tenant
identifiers. Older audit migrations used BIGINT tenant/entity identifiers,
which prevented audit outbox writes and hid movement history for text-code
companies. This migration is idempotent for already-created tenant databases.
"""
from alembic import op


revision = "025e_audit_text_tenant_repair"
down_revision = "025d_notifications_schema_repair"
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

        ALTER TABLE audit_outbox
            ALTER COLUMN tenant_id TYPE VARCHAR(100) USING tenant_id::text,
            ALTER COLUMN entity_id TYPE VARCHAR(100) USING entity_id::text,
            ALTER COLUMN tenant_id SET NOT NULL;

        CREATE INDEX IF NOT EXISTS ix_audit_outbox_pending
            ON audit_outbox (tenant_id, enqueued_at)
            WHERE flushed_at IS NULL;

        DO $$
        BEGIN
            IF to_regclass('public.audit_logs') IS NOT NULL THEN
                ALTER TABLE audit_logs
                    ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS critical BOOLEAN NOT NULL DEFAULT false;

                ALTER TABLE audit_logs
                    ALTER COLUMN tenant_id TYPE VARCHAR(100) USING tenant_id::text;

                PERFORM set_config('audit_logs.allow_admin_op', 'retention', true);

                UPDATE audit_logs
                   SET tenant_id = COALESCE(
                       NULLIF(tenant_id, ''),
                       NULLIF(regexp_replace(current_database(), '^aman_', ''), ''),
                       'unknown'
                   )
                 WHERE tenant_id IS NULL OR tenant_id = '';

                CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_action_created
                    ON audit_logs (tenant_id, action, created_at DESC);
            END IF;
        END $$;

        CREATE OR REPLACE FUNCTION tg_treasury_balance_authority_fn()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        DECLARE
            _gl_ctx TEXT;
        BEGIN
            _gl_ctx := current_setting('aman.gl_context', true);
            IF _gl_ctx IS DISTINCT FROM 'on' THEN
                INSERT INTO audit_outbox
                    (tenant_id, actor_id, action, entity_type, entity_id,
                     payload, critical, enqueued_at)
                VALUES
                    (COALESCE(
                         NULLIF(current_setting('app.tenant_id', true), ''),
                         NULLIF(regexp_replace(current_database(), '^aman_', ''), ''),
                         'unknown'
                     ),
                     NULL,
                     'treasury.balance.blocked',
                     'treasury_account',
                     OLD.id::text,
                     jsonb_build_object(
                         'old_balance', OLD.current_balance,
                         'attempted_balance', NEW.current_balance,
                         'session_aman_gl_context', COALESCE(_gl_ctx, '<unset>')
                     ),
                     true,
                     clock_timestamp());

                RAISE EXCEPTION
                    'Direct treasury balance update blocked - set aman.gl_context = ''on'' first'
                    USING ERRCODE = 'P0001';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_audit_logs_tenant_action_created;
        DROP INDEX IF EXISTS ix_audit_outbox_pending;
        """
    )

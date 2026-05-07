"""022f: Treasury balance authority trigger.

Revision: 022f_treasury_balance_trigger
Revises: 022g_je_source_normalize
Create Date: 2026-05-02

Creates a BEFORE UPDATE trigger on ``treasury_accounts.current_balance``
that blocks direct balance writes unless the session has set
``aman.gl_context = 'on'``.  Blocked attempts are logged to the audit
outbox.
"""
from alembic import op


revision = "022f_treasury_balance_trigger"
down_revision = "022g_je_source_normalize"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- 1. Trigger function
        CREATE OR REPLACE FUNCTION tg_treasury_balance_authority_fn()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        DECLARE
            _gl_ctx TEXT;
        BEGIN
            _gl_ctx := current_setting('aman.gl_context', true);
            IF _gl_ctx IS DISTINCT FROM 'on' THEN
                -- Audit: log the blocked attempt
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
                    'Direct treasury balance update blocked — set aman.gl_context = ''on'' first'
                    USING ERRCODE = 'P0001';
            END IF;
            RETURN NEW;
        END;
        $$;

        -- 2. Trigger
        DROP TRIGGER IF EXISTS tg_treasury_balance_authority ON treasury_accounts;

        CREATE TRIGGER tg_treasury_balance_authority
            BEFORE UPDATE OF current_balance
            ON treasury_accounts
            FOR EACH ROW
            EXECUTE FUNCTION tg_treasury_balance_authority_fn();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS tg_treasury_balance_authority ON treasury_accounts;
        DROP FUNCTION IF EXISTS tg_treasury_balance_authority_fn();
        """
    )

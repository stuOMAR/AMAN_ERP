"""T3.7: audit_logs hash chain + DB-level immutability trigger.

Audit items #21, #22, #23, #25, #26, #137 — the audit trail had no
tamper-evidence (no hash chain, no DB trigger blocking UPDATE/DELETE)
and two write paths (`utils.audit.log_activity` and inline INSERTs in
`utils.permissions`) bypassed each other.

This migration:

  1. Adds three columns to ``audit_logs``::

         prev_hash  CHAR(64)            -- SHA-256 of previous row in chain
         hash       CHAR(64) NOT NULL   -- SHA-256 of this row's payload
         chain_seq  BIGINT  NOT NULL    -- 1-based monotonic position

  2. Backfills the chain over existing rows in id order so the
     chain is verifiable from the beginning of history.

  3. Installs ``audit_logs_immutable_trigger`` rejecting UPDATE/DELETE
     unless the session set ``audit_logs.allow_admin_op`` (used by the
     retention scheduler for archival/7-year purge). When the flag is
     set, only ``is_archived``/``archived_at`` may change on UPDATE so
     the chain payload remains intact.
"""
from alembic import op


revision = "0017_audit_logs_hash_chain_immutability"
down_revision = "0016_invoice_clearance_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- 1. Schema additions (idempotent for re-runs).
        ALTER TABLE audit_logs
            ADD COLUMN IF NOT EXISTS prev_hash VARCHAR(64),
            ADD COLUMN IF NOT EXISTS hash      VARCHAR(64),
            ADD COLUMN IF NOT EXISTS chain_seq BIGINT;

        -- 2. Backfill in id order. We compute SHA-256 of a canonical
        --    pipe-joined payload per row, threading prev_hash through
        --    the loop so any single tampering breaks downstream hashes.
        DO $backfill$
        DECLARE
            r          RECORD;
            seq        BIGINT := 0;
            prev       TEXT   := '';
            payload    TEXT;
            new_hash   TEXT;
        BEGIN
            -- Only backfill if any rows still lack a hash.
            IF EXISTS (SELECT 1 FROM audit_logs WHERE hash IS NULL) THEN
                FOR r IN SELECT * FROM audit_logs ORDER BY id LOOP
                    seq := seq + 1;
                    payload := concat_ws('|',
                        prev,
                        seq::TEXT,
                        COALESCE(r.user_id::TEXT, ''),
                        COALESCE(r.username, ''),
                        COALESCE(r.action, ''),
                        COALESCE(r.resource_type, ''),
                        COALESCE(r.resource_id, ''),
                        COALESCE(r.details::TEXT, '{}'),
                        COALESCE(r.ip_address, ''),
                        COALESCE(r.branch_id::TEXT, ''),
                        COALESCE(to_char(r.created_at AT TIME ZONE 'UTC',
                                         'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), '')
                    );
                    new_hash := encode(digest(payload, 'sha256'), 'hex');
                    UPDATE audit_logs
                       SET prev_hash = prev,
                           hash      = new_hash,
                           chain_seq = seq
                     WHERE id = r.id;
                    prev := new_hash;
                END LOOP;
            END IF;
        END
        $backfill$;

        -- pgcrypto ships with the contrib package the digest() call above
        -- needs; ensure it's available.
        CREATE EXTENSION IF NOT EXISTS pgcrypto;

        -- 3. Constraints (after backfill so existing rows are valid).
        ALTER TABLE audit_logs
            ALTER COLUMN hash      SET NOT NULL,
            ALTER COLUMN chain_seq SET NOT NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS ux_audit_logs_chain_seq
            ON audit_logs (chain_seq);

        -- 4. Immutability trigger.
        CREATE OR REPLACE FUNCTION audit_logs_immutable_fn()
        RETURNS trigger AS $$
        DECLARE
            allowed TEXT;
        BEGIN
            BEGIN
                allowed := current_setting('audit_logs.allow_admin_op', true);
            EXCEPTION WHEN OTHERS THEN
                allowed := NULL;
            END;

            IF allowed IS NULL OR allowed = '' THEN
                RAISE EXCEPTION
                    'audit_logs is append-only (T3.7 audit #21) — set audit_logs.allow_admin_op for retention jobs';
            END IF;

            -- Even with the flag set, restrict UPDATE to archival fields
            -- so the hash-chain payload stays immutable.
            IF TG_OP = 'UPDATE' THEN
                IF OLD.id          IS DISTINCT FROM NEW.id          OR
                   OLD.user_id     IS DISTINCT FROM NEW.user_id     OR
                   OLD.username    IS DISTINCT FROM NEW.username    OR
                   OLD.action      IS DISTINCT FROM NEW.action      OR
                   OLD.resource_type IS DISTINCT FROM NEW.resource_type OR
                   OLD.resource_id IS DISTINCT FROM NEW.resource_id OR
                   OLD.details     IS DISTINCT FROM NEW.details     OR
                   OLD.ip_address  IS DISTINCT FROM NEW.ip_address  OR
                   OLD.branch_id   IS DISTINCT FROM NEW.branch_id   OR
                   OLD.created_at  IS DISTINCT FROM NEW.created_at  OR
                   OLD.prev_hash   IS DISTINCT FROM NEW.prev_hash   OR
                   OLD.hash        IS DISTINCT FROM NEW.hash        OR
                   OLD.chain_seq   IS DISTINCT FROM NEW.chain_seq THEN
                    RAISE EXCEPTION
                        'audit_logs UPDATE limited to is_archived/archived_at';
                END IF;
            END IF;

            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS audit_logs_no_update ON audit_logs;
        DROP TRIGGER IF EXISTS audit_logs_no_delete ON audit_logs;
        CREATE TRIGGER audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable_fn();
        CREATE TRIGGER audit_logs_no_delete
            BEFORE DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable_fn();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS audit_logs_no_update ON audit_logs;
        DROP TRIGGER IF EXISTS audit_logs_no_delete ON audit_logs;
        DROP FUNCTION IF EXISTS audit_logs_immutable_fn();
        DROP INDEX IF EXISTS ux_audit_logs_chain_seq;
        ALTER TABLE audit_logs
            DROP COLUMN IF EXISTS chain_seq,
            DROP COLUMN IF EXISTS hash,
            DROP COLUMN IF EXISTS prev_hash;
        """
    )

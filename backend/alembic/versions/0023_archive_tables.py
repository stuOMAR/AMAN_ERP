"""T9.3 — Archive tables for inventory_transactions and audit_logs.

Revision: 0023_archive_tables
Revises: 0022_unified_search_vectors
Create Date: 2026-05-01

Per Phase 9 DoD: the live `inventory_transactions` and `audit_logs` tables
accumulate indefinitely and become a query-cost liability. This migration
adds *_archive mirror tables with the same column shape (minus FKs and
defaults — archives are write-only). A monthly scheduler job moves rows
older than the retention window from the live table into the archive.

For audit_logs we keep the existing `is_archived`/`archived_at` flags on
the *live* table (used by short-term retention soft-delete) AND add the
new `audit_logs_archive` table for long-term cold storage of records
older than 7 years.

Idempotent: every CREATE is `IF NOT EXISTS`, safe to re-run.
"""
from alembic import op


revision = "0023_archive_tables"
down_revision = "0022_unified_search_vectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- =============================================================
        -- inventory_transactions_archive — cold storage > 7 years.
        -- =============================================================
        CREATE TABLE IF NOT EXISTS inventory_transactions_archive (
            id                  INTEGER       PRIMARY KEY,
            product_id          INTEGER,
            warehouse_id        INTEGER,
            transaction_type    VARCHAR(50)   NOT NULL,
            reference_type      VARCHAR(50),
            reference_id        INTEGER,
            reference_document  VARCHAR(100),
            quantity            DECIMAL(18, 4) NOT NULL,
            balance_before      DECIMAL(18, 4),
            balance_after       DECIMAL(18, 4),
            unit_cost           DECIMAL(18, 4),
            total_cost          DECIMAL(18, 4),
            notes               TEXT,
            created_by          INTEGER,
            created_at          TIMESTAMPTZ   NOT NULL,
            archived_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_inv_tx_arch_created
            ON inventory_transactions_archive (created_at);
        CREATE INDEX IF NOT EXISTS idx_inv_tx_arch_product
            ON inventory_transactions_archive (product_id);

        -- =============================================================
        -- audit_logs_archive — cold storage > 7 years.
        -- The hash chain columns are preserved so forensic verification
        -- can still walk the chain across archive boundaries.
        -- =============================================================
        CREATE TABLE IF NOT EXISTS audit_logs_archive (
            id              INTEGER       PRIMARY KEY,
            user_id         INTEGER,
            username        VARCHAR(100),
            action          VARCHAR(100),
            resource_type   VARCHAR(50),
            resource_id     VARCHAR(50),
            details         JSONB,
            ip_address      VARCHAR(50),
            branch_id       INTEGER,
            prev_hash       VARCHAR(64),
            hash            VARCHAR(64),
            chain_seq       BIGINT,
            created_at      TIMESTAMPTZ   NOT NULL,
            archived_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_audit_logs_arch_created
            ON audit_logs_archive (created_at);
        CREATE INDEX IF NOT EXISTS idx_audit_logs_arch_user
            ON audit_logs_archive (user_id);
        CREATE INDEX IF NOT EXISTS idx_audit_logs_arch_chain
            ON audit_logs_archive (chain_seq);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS inventory_transactions_archive;
        DROP TABLE IF EXISTS audit_logs_archive;
        """
    )

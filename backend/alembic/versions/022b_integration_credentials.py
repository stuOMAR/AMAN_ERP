"""022b: Create integration_credentials table.

Revision: 022b_integration_credentials
Revises: 022a_audit_outbox
Create Date: 2026-05-02

Single vault for all integration secrets.  See data-model.md § integration_credentials.
"""
from alembic import op


revision = "022b_integration_credentials"
down_revision = "022a_audit_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- 1. Main table
        CREATE TABLE IF NOT EXISTS integration_credentials (
            id                   BIGSERIAL     PRIMARY KEY,
            tenant_id            BIGINT        NOT NULL,
            integration          VARCHAR(32)   NOT NULL,
            name                 VARCHAR(128)  NOT NULL,
            secret_ciphertext    BYTEA         NOT NULL,
            key_version          INT           NOT NULL DEFAULT 1,
            metadata             JSONB         NOT NULL DEFAULT '{}',
            status               VARCHAR(16)   NOT NULL DEFAULT 'active',
            consecutive_failures INT           NOT NULL DEFAULT 0,
            rotated_at           TIMESTAMPTZ   NULL,
            expires_at           TIMESTAMPTZ   NULL,
            created_by           BIGINT        NULL,
            created_at           TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp(),
            deleted_at           TIMESTAMPTZ   NULL,
            updated_at           TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp()
        );

        -- 2. Partial unique index: one active/rotating row per (tenant, integration, name)
        CREATE UNIQUE INDEX IF NOT EXISTS uq_cred_tenant_integ_name
            ON integration_credentials (tenant_id, integration, name)
            WHERE status != 'soft_deleted';

        -- 3. Lookup index for tenant-scoped queries
        CREATE INDEX IF NOT EXISTS ix_cred_tenant_integration
            ON integration_credentials (tenant_id, integration);

        -- 4. Rotation expiry sweep index
        CREATE INDEX IF NOT EXISTS ix_cred_rotating_expiry
            ON integration_credentials (status, expires_at)
            WHERE status = 'rotating';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_cred_rotating_expiry;
        DROP INDEX IF EXISTS ix_cred_tenant_integration;
        DROP INDEX IF EXISTS uq_cred_tenant_integ_name;
        DROP TABLE IF EXISTS integration_credentials;
        """
    )

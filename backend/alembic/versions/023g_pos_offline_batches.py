"""023g: POS offline batches table.

Revision: 023g_pos_offline_batches
Revises: 023d_acc_map_sales_consolidation
Create Date: 2026-05-02
"""
from alembic import op


revision = "023g_pos_offline_batches"
down_revision = "023d_acc_map_sales_consolidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_offline_batches (
            id                  BIGSERIAL       PRIMARY KEY,
            tenant_id           BIGINT          NOT NULL,
            device_id           VARCHAR(64)     NOT NULL,
            client_uuid         UUID            NOT NULL,
            state               VARCHAR(20)     NOT NULL DEFAULT 'queued',
            payload             JSONB           NOT NULL DEFAULT '{}',
            pos_sale_id         BIGINT,
            failure_reason_code VARCHAR(32),
            failure_detail      TEXT,
            queued_at           TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
            processed_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
        );

        ALTER TABLE pos_offline_batches
            DROP CONSTRAINT IF EXISTS chk_pos_offline_state;
        ALTER TABLE pos_offline_batches
            ADD CONSTRAINT chk_pos_offline_state
            CHECK (state IN ('queued','reconciling','committed','manual_review','failed'));

        -- Idempotency: one batch per device + client UUID
        CREATE UNIQUE INDEX IF NOT EXISTS uix_pos_offline_device_uuid
            ON pos_offline_batches (tenant_id, device_id, client_uuid);

        -- Worker index: queued batches
        CREATE INDEX IF NOT EXISTS ix_pos_offline_queued
            ON pos_offline_batches (tenant_id, state, queued_at)
            WHERE state = 'queued';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_pos_offline_queued;
        DROP INDEX IF EXISTS uix_pos_offline_device_uuid;
        ALTER TABLE pos_offline_batches DROP CONSTRAINT IF EXISTS chk_pos_offline_state;
        DROP TABLE IF EXISTS pos_offline_batches;
        """
    )

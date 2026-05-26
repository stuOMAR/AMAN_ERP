"""031h: search query logs and tenant ID types repair

Revision ID: 031h_search_query_logs_and_tenant_types
Revises: 031g_integrations_dms_notifications_imports
"""
from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "031h_search_query_logs_and_tenant_types"
down_revision: Union[str, None] = "031g_integrations_dms_notifications_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- Create search_query_logs table
        CREATE TABLE IF NOT EXISTS search_query_logs (
            id BIGSERIAL PRIMARY KEY,
            tenant_id VARCHAR(100) NOT NULL,
            actor_id VARCHAR(50),
            query VARCHAR(256) NOT NULL,
            result_count INT NOT NULL DEFAULT 0,
            latency_ms INT NOT NULL DEFAULT 0,
            entity_hits JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        );

        CREATE INDEX IF NOT EXISTS idx_search_query_logs_tenant_query
            ON search_query_logs (tenant_id, query);

        -- Alter notifications_queue.tenant_id to VARCHAR(100)
        ALTER TABLE notifications_queue ALTER COLUMN tenant_id TYPE VARCHAR(100) USING tenant_id::varchar;

        -- Alter email_templates.tenant_id to VARCHAR(100)
        ALTER TABLE email_templates ALTER COLUMN tenant_id TYPE VARCHAR(100) USING tenant_id::varchar;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_search_query_logs_tenant_query;
        DROP TABLE IF EXISTS search_query_logs;
        """
    )

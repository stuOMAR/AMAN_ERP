"""025b: Create KPI definition and evaluation tables.

Revision: 025b_kpi_tables
Revises: 025a_audit_outbox_repair
Create Date: 2026-05-02
"""
from alembic import op


revision = "025b_kpi_tables"
down_revision = "025a_audit_outbox_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kpi_definitions (
            id UUID PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            kpi_code VARCHAR(128) NOT NULL,
            metric_source VARCHAR(32) NOT NULL,
            metric_reference TEXT NOT NULL,
            threshold_value NUMERIC(18, 4) NOT NULL,
            comparison_op VARCHAR(8) NOT NULL,
            channels JSONB NOT NULL DEFAULT '[]'::jsonb,
            evaluation_interval_minutes INT NOT NULL DEFAULT 15,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_by BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT uq_kpi_definitions_tenant_code UNIQUE (tenant_id, kpi_code),
            CONSTRAINT ck_kpi_metric_source CHECK (metric_source IN ('report_key', 'classifier_category')),
            CONSTRAINT ck_kpi_comparison_op CHECK (comparison_op IN ('lt', 'lte', 'gt', 'gte', 'eq')),
            CONSTRAINT ck_kpi_interval CHECK (evaluation_interval_minutes >= 5)
        );

        CREATE INDEX IF NOT EXISTS idx_kpi_definitions_active
            ON kpi_definitions (tenant_id, is_active, evaluation_interval_minutes);

        CREATE TABLE IF NOT EXISTS kpi_evaluations (
            id BIGSERIAL PRIMARY KEY,
            kpi_id UUID NOT NULL REFERENCES kpi_definitions(id) ON DELETE CASCADE,
            tenant_id BIGINT NOT NULL,
            evaluation_window_start TIMESTAMPTZ NOT NULL,
            evaluation_window_end TIMESTAMPTZ NOT NULL,
            value NUMERIC(18, 4) NOT NULL,
            breached BOOLEAN NOT NULL DEFAULT false,
            notified_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT uq_kpi_evaluations_window UNIQUE (kpi_id, evaluation_window_start)
        );

        CREATE INDEX IF NOT EXISTS idx_kpi_evaluations_tenant_created
            ON kpi_evaluations (tenant_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_kpi_evaluations_pending_notifications
            ON kpi_evaluations (tenant_id, breached, notified_at)
            WHERE breached = true AND notified_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_kpi_evaluations_pending_notifications;
        DROP INDEX IF EXISTS idx_kpi_evaluations_tenant_created;
        DROP TABLE IF EXISTS kpi_evaluations;
        DROP INDEX IF EXISTS idx_kpi_definitions_active;
        DROP TABLE IF EXISTS kpi_definitions;
        """
    )
"""023f: Opportunity stage history table.

Revision: 023f_opportunity_stage_history
Revises: 023d_acc_map_sales_consolidation
Create Date: 2026-05-02
"""
from alembic import op


revision = "023f_opportunity_stage_history"
down_revision = "023d_acc_map_sales_consolidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS opportunity_stage_history (
            id              BIGSERIAL       PRIMARY KEY,
            tenant_id       BIGINT          NOT NULL,
            opportunity_id  BIGINT          NOT NULL,
            from_stage      VARCHAR(32),
            to_stage        VARCHAR(32)     NOT NULL,
            entered_at      TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
            actor_id        BIGINT,
            reason          TEXT,
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
        );

        CREATE INDEX IF NOT EXISTS ix_opp_stage_history_lookup
            ON opportunity_stage_history (tenant_id, opportunity_id, entered_at);

        CREATE INDEX IF NOT EXISTS ix_opp_stage_history_funnel
            ON opportunity_stage_history (tenant_id, to_stage, entered_at);

        -- Seed initial rows from current opportunities.stage
        INSERT INTO opportunity_stage_history (tenant_id, opportunity_id, to_stage, entered_at, actor_id)
        SELECT tenant_id, id, stage, COALESCE(updated_at, created_at), NULL
        FROM opportunities
        WHERE stage IS NOT NULL
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_opp_stage_history_funnel;
        DROP INDEX IF EXISTS ix_opp_stage_history_lookup;
        DROP TABLE IF EXISTS opportunity_stage_history;
        """
    )

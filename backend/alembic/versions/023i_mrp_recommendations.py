"""023i: MRP recommendations table.

Revision: 023i_mrp_recommendations
Revises: 023d_acc_map_sales_consolidation
Create Date: 2026-05-02
"""
from alembic import op


revision = "023i_mrp_recommendations"
down_revision = "023d_acc_map_sales_consolidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mrp_recommendations (
            id              BIGSERIAL       PRIMARY KEY,
            tenant_id       BIGINT          NOT NULL,
            run_id          UUID            NOT NULL,
            item_id         BIGINT          NOT NULL,
            warehouse_id    BIGINT          NOT NULL,
            recommended_qty NUMERIC(18,4),
            due_date        DATE,
            supplier_id     BIGINT,
            state           VARCHAR(20)     NOT NULL DEFAULT 'open',
            po_id           BIGINT,
            reason          TEXT,
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp(),
            updated_at      TIMESTAMPTZ     NOT NULL DEFAULT clock_timestamp()
        );

        ALTER TABLE mrp_recommendations
            DROP CONSTRAINT IF EXISTS chk_mrp_rec_state;
        ALTER TABLE mrp_recommendations
            ADD CONSTRAINT chk_mrp_rec_state
            CHECK (state IN ('open','accepted','dismissed','converted_to_po'));

        CREATE INDEX IF NOT EXISTS ix_mrp_recommendations_state
            ON mrp_recommendations (tenant_id, state, run_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_mrp_recommendations_state;
        ALTER TABLE mrp_recommendations DROP CONSTRAINT IF EXISTS chk_mrp_rec_state;
        DROP TABLE IF EXISTS mrp_recommendations;
        """
    )

"""add project retainer columns

Revision ID: 0003_add_project_retainer_columns
Revises: 0002_drop_campaign_cols
Create Date: 2026-04-20

Add retainer_amount, billing_cycle, and next_billing_date columns to
the projects table to support retainer-based billing workflows (FR-009).

Constitution XXVIII: Applied together with database.py CREATE TABLE update.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0003_add_project_retainer_columns"
down_revision = "0002_drop_campaign_cols"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("projects")]
    
    if "retainer_amount" not in columns:
        op.add_column(
            "projects",
            sa.Column("retainer_amount", sa.Numeric(18, 4), server_default="0", nullable=True),
        )
    if "billing_cycle" not in columns:
        op.add_column(
            "projects",
            sa.Column("billing_cycle", sa.String(20), nullable=True),
        )
    if "next_billing_date" not in columns:
        op.add_column(
            "projects",
            sa.Column("next_billing_date", sa.Date(), nullable=True),
        )


def downgrade():
    op.drop_column("projects", "next_billing_date")
    op.drop_column("projects", "billing_cycle")
    op.drop_column("projects", "retainer_amount")

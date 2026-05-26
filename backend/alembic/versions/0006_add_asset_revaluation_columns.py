"""add asset revaluation columns

Revision ID: 0006_add_asset_revaluation_columns
Revises: 0005_widen_asset_money_columns
Create Date: 2026-04-20

Add current_value and revaluation_surplus columns to the assets table.
current_value tracks the revalued carrying amount (separate from historical
cost), and revaluation_surplus tracks cumulative IAS 16.39-40 surplus.
Backfill current_value = cost for existing rows.

Constitution XXVIII: Applied together with database.py CREATE TABLE update.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0006_add_asset_revaluation_columns"
down_revision = "0005_widen_asset_money_columns"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("assets")]
    
    if "current_value" not in columns:
        op.add_column(
            "assets",
            sa.Column("current_value", sa.Numeric(18, 4), nullable=True),
        )
    if "revaluation_surplus" not in columns:
        op.add_column(
            "assets",
            sa.Column("revaluation_surplus", sa.Numeric(18, 4), server_default="0", nullable=True),
        )
    # Backfill: set current_value = cost for existing rows
    op.execute("UPDATE assets SET current_value = cost WHERE current_value IS NULL")


def downgrade():
    op.drop_column("assets", "revaluation_surplus")
    op.drop_column("assets", "current_value")

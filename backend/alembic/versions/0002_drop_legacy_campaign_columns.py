"""drop legacy campaign metric columns

Revision ID: 0002_drop_legacy_campaign_columns
Revises: 0001_baseline_complete
Create Date: 2026-04-20

Remove the four stale metric columns from marketing_campaigns that were
superseded by the total_* column family written by the campaign execute
endpoint. These columns were never written after the schema was updated and
always contained zeros, causing all analytics to return empty data.

Constitution XXVIII: Applied together with database.py CREATE TABLE update.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002_drop_campaign_cols"
down_revision = "0001_baseline_complete"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    if "marketing_campaigns" in tables:
        columns = [c["name"] for c in inspector.get_columns("marketing_campaigns")]
        for col in ["sent_count", "open_count", "click_count", "conversion_count"]:
            if col in columns:
                op.drop_column("marketing_campaigns", col)


def downgrade():
    op.add_column(
        "marketing_campaigns",
        sa.Column("sent_count", sa.Integer(), server_default="0", nullable=True),
    )
    op.add_column(
        "marketing_campaigns",
        sa.Column("open_count", sa.Integer(), server_default="0", nullable=True),
    )
    op.add_column(
        "marketing_campaigns",
        sa.Column("click_count", sa.Integer(), server_default="0", nullable=True),
    )
    op.add_column(
        "marketing_campaigns",
        sa.Column("conversion_count", sa.Integer(), server_default="0", nullable=True),
    )

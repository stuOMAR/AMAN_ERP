"""Payroll period overlap prevention.

Feature 024 — T011. Adds state column + tstzrange exclusion constraint.
"""
from alembic import op
import sqlalchemy as sa

revision = "024b_payroll_period_overlap"
down_revision = "024a_hr_pii_encryption"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.add_column("payroll_periods", sa.Column(
        "state", sa.String(16), nullable=False, server_default="draft",
    ))

    # Exclusion constraint: no overlapping periods unless reversed
    op.execute("""
        ALTER TABLE payroll_periods
        ADD CONSTRAINT excl_payroll_period_overlap
        EXCLUDE USING gist (
            tenant_id WITH =,
            tstzrange(start_date, end_date, '[]') WITH &&
        ) WHERE (state <> 'reversed')
    """)


def downgrade() -> None:
    op.drop_constraint("excl_payroll_period_overlap", "payroll_periods", type_="exclusion")
    op.drop_column("payroll_periods", "state")

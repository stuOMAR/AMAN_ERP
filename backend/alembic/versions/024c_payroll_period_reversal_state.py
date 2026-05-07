"""Payroll run reversal state.

Feature 024 — T020. Adds wps_superseded_by_run_id to payroll_runs.
"""
from alembic import op
import sqlalchemy as sa

revision = "024c_payroll_period_reversal_state"
down_revision = "024b_payroll_period_overlap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payroll_runs", sa.Column(
        "wps_superseded_by_run_id", sa.BigInteger(), nullable=True,
    ))
    op.create_foreign_key(
        "fk_payroll_runs_superseded", "payroll_runs", "payroll_runs",
        ["wps_superseded_by_run_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_payroll_runs_superseded", "payroll_runs", type_="foreignkey")
    op.drop_column("payroll_runs", "wps_superseded_by_run_id")

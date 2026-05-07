"""Payslip uniqueness constraint.

Feature 024 — T021. Backfill duplicates, add unique (tenant_id, employee_id, period_id).
"""
from alembic import op
import sqlalchemy as sa

revision = "024d_payslip_uniqueness"
down_revision = "024c_payroll_period_reversal_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backfill: keep only the latest run_id for each (tenant, employee, period)
    op.execute("""
        DELETE FROM payslips a USING payslips b
        WHERE a.tenant_id = b.tenant_id
          AND a.employee_id = b.employee_id
          AND a.period_id = b.period_id
          AND a.id < b.id
          AND a.deleted_at IS NULL
    """)

    op.create_index(
        "uq_payslip_tenant_emp_period",
        "payslips",
        ["tenant_id", "employee_id", "period_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_payslip_tenant_emp_period", table_name="payslips")

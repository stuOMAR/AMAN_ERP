"""Maintenance plans table.

Feature 024 — T059.
"""
from alembic import op
import sqlalchemy as sa

revision = "024l_maintenance_plans"
down_revision = "024k_technicians_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "maintenance_plans",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=True),
        sa.Column("equipment_id", sa.BigInteger(), nullable=True),
        sa.Column("contract_id", sa.BigInteger(), nullable=True),
        sa.Column("cadence", sa.JSON(), nullable=False),
        sa.Column("template_service_order_id", sa.BigInteger(), nullable=True),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
    )
    op.create_index("ix_maint_plans_tenant_due", "maintenance_plans", ["tenant_id", "next_due_at", "active"])


def downgrade() -> None:
    op.drop_table("maintenance_plans")

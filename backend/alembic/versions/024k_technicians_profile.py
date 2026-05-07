"""Technicians profile table.

Feature 024 — T054.
"""
from alembic import op
import sqlalchemy as sa

revision = "024k_technicians_profile"
down_revision = "024j_service_orders_extension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "technicians",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("employee_id", sa.BigInteger(), nullable=True),
        sa.Column("external_name", sa.String(255), nullable=True),
        sa.Column("skills", sa.JSON(), nullable=True),
        sa.Column("zones", sa.JSON(), nullable=True),
        sa.Column("certifications", sa.JSON(), nullable=True),
        sa.Column("availability", sa.JSON(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
    )
    op.create_foreign_key("fk_technician_employee", "technicians", "employees", ["employee_id"], ["id"])
    op.create_index("ix_technicians_tenant", "technicians", ["tenant_id", "active"])


def downgrade() -> None:
    op.drop_table("technicians")

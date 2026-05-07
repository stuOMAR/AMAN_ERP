"""Service orders extension.

Feature 024 — T046. Adds kind, technician, pricelist, revenue/cost/margin fields.
"""
from alembic import op
import sqlalchemy as sa

revision = "024j_service_orders_extension"
down_revision = "024i_service_contracts_extension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service_orders", sa.Column("kind", sa.String(32), nullable=True))
    op.add_column("service_orders", sa.Column("assigned_technician_id", sa.BigInteger(), nullable=True))
    op.add_column("service_orders", sa.Column("pricelist_source_level", sa.String(16), nullable=True))
    op.add_column("service_orders", sa.Column("revenue_total", sa.Numeric(18, 4), nullable=True))
    op.add_column("service_orders", sa.Column("cost_total", sa.Numeric(18, 4), nullable=True))
    op.add_column("service_orders", sa.Column("margin_amount", sa.Numeric(18, 4), nullable=True))
    op.add_column("service_orders", sa.Column("margin_pct", sa.Numeric(7, 4), nullable=True))
    op.add_column("service_orders", sa.Column("revenue_resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("service_orders", sa.Column("contract_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_so_technician", "service_orders", "technicians", ["assigned_technician_id"], ["id"])
    op.create_foreign_key("fk_so_contract", "service_orders", "service_contracts", ["contract_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_so_contract", "service_orders", type_="foreignkey")
    op.drop_constraint("fk_so_technician", "service_orders", type_="foreignkey")
    for col in ["contract_id", "revenue_resolved_at", "margin_pct", "margin_amount",
                "cost_total", "revenue_total", "pricelist_source_level",
                "assigned_technician_id", "kind"]:
        op.drop_column("service_orders", col)

"""Service pricelists table.

Feature 024 — T044.
"""
from alembic import op
import sqlalchemy as sa

revision = "024h_service_pricelists"
down_revision = "024g_payroll_entries_period_id_align"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_pricelists",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),  # tenant/customer/contract
        sa.Column("scope_ref_id", sa.BigInteger(), nullable=True),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
    )
    op.create_index(
        "uq_pricelist_scope_item_from", "service_pricelists",
        ["tenant_id", "scope", "scope_ref_id", "item_id", "valid_from"],
        unique=True,
    )
    op.create_index("ix_pricelist_tenant_item", "service_pricelists", ["tenant_id", "item_id", "active"])


def downgrade() -> None:
    op.drop_table("service_pricelists")

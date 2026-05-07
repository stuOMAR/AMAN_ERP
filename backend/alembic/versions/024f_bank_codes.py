"""Bank codes reference table.

Feature 024 — T032. Creates bank_codes table with seed data.
"""
from alembic import op
import sqlalchemy as sa

revision = "024f_bank_codes"
down_revision = "024e_acc_map_loans_advances_split"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bank_codes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name_en", sa.String(255), nullable=False),
        sa.Column("name_ar", sa.String(255), nullable=True),
        sa.Column("swift_bic", sa.String(16), nullable=True),
        sa.Column("wps_routing_code", sa.String(32), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
    )
    op.create_index("uq_bank_codes_tenant_code", "bank_codes", ["tenant_id", "code"], unique=True)
    op.create_index("uq_bank_codes_tenant_swift", "bank_codes", ["tenant_id", "swift_bic"], unique=True, postgresql_where=sa.text("swift_bic IS NOT NULL"))


def downgrade() -> None:
    op.drop_table("bank_codes")

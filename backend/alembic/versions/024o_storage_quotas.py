"""Storage quotas snapshot table.

Feature 024 — T069.
"""
from alembic import op
import sqlalchemy as sa

revision = "024o_storage_quotas"
down_revision = "024n_documents_scan_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_quotas",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),  # tenant/user
        sa.Column("scope_ref_id", sa.BigInteger(), nullable=True),
        sa.Column("used_bytes", sa.BigInteger(), server_default="0"),
        sa.Column("quota_bytes", sa.BigInteger(), nullable=False),
        sa.Column("last_recalculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
    )
    op.create_index("uq_storage_quota_scope", "storage_quotas", ["tenant_id", "scope", "scope_ref_id"], unique=True)


def downgrade() -> None:
    op.drop_table("storage_quotas")

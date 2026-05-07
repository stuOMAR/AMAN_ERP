"""Approval tokens table.

Feature 024 — T013.
"""
from alembic import op
import sqlalchemy as sa

revision = "024r_approval_tokens"
down_revision = "024q_email_templates_finalize"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_tokens",
        sa.Column("nonce", sa.CHAR(32), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("issuer_user_id", sa.BigInteger(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("consumed_via_ip", sa.String(45), nullable=True),
    )
    op.create_index(
        "uq_token_nonce_unconsumed", "approval_tokens",
        ["nonce"],
        unique=True,
        postgresql_where=sa.text("consumed_at IS NULL"),
    )
    op.create_index("ix_token_tenant_action", "approval_tokens", ["tenant_id", "action"])


def downgrade() -> None:
    op.drop_table("approval_tokens")

"""Notifications queue table.

Feature 024 — T012.
"""
from alembic import op
import sqlalchemy as sa

revision = "024p_notifications_queue"
down_revision = "024o_storage_quotas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications_queue",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.CHAR(32), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("recipient", sa.String(512), nullable=False),
        sa.Column("template_code", sa.String(64), nullable=True),
        sa.Column("locale", sa.CHAR(5), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("state", sa.String(16), server_default="pending"),
        sa.Column("attempts", sa.SmallInteger(), server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dlq_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
    )
    op.create_index(
        "uq_notif_inflight", "notifications_queue",
        ["tenant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("state IN ('pending','sending')"),
    )
    op.create_index("ix_notif_worker", "notifications_queue", ["channel", "state", "next_attempt_at"])
    op.create_index("ix_notif_dlq", "notifications_queue", ["state", "dlq_at"])


def downgrade() -> None:
    op.drop_table("notifications_queue")

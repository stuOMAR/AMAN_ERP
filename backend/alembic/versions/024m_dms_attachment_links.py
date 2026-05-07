"""DMS attachment links table.

Feature 024 — T067.
"""
from alembic import op
import sqlalchemy as sa

revision = "024m_dms_attachment_links"
down_revision = "024l_maintenance_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dms_attachment_links",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("link_role", sa.String(64), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
    )
    op.create_foreign_key("fk_att_link_doc", "dms_attachment_links", "documents", ["document_id"], ["id"])
    op.create_index("uq_att_link_unique", "dms_attachment_links",
                     ["tenant_id", "document_id", "entity_type", "entity_id", "link_role"], unique=True)
    op.create_index("ix_att_link_entity", "dms_attachment_links", ["entity_type", "entity_id"])
    op.create_index("ix_att_link_document", "dms_attachment_links", ["document_id"])


def downgrade() -> None:
    op.drop_table("dms_attachment_links")

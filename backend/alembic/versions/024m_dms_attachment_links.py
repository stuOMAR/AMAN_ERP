"""DMS attachment links table.

Feature 024 — T067.
"""
from alembic import op

revision = "024m_dms_attachment_links"
down_revision = "024l_maintenance_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS dms_attachment_links (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            entity_type VARCHAR(64) NOT NULL,
            entity_id BIGINT NOT NULL,
            link_role VARCHAR(64),
            created_by_user_id BIGINT,
            created_at TIMESTAMPTZ DEFAULT clock_timestamp()
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_att_link_unique
            ON dms_attachment_links (tenant_id, document_id, entity_type, entity_id, COALESCE(link_role, ''));
        CREATE INDEX IF NOT EXISTS ix_att_link_entity
            ON dms_attachment_links (entity_type, entity_id);
        CREATE INDEX IF NOT EXISTS ix_att_link_document
            ON dms_attachment_links (document_id);
    """)


def downgrade() -> None:
    op.drop_table("dms_attachment_links")

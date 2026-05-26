"""Storage quotas snapshot table.

Feature 024 — T069.
"""
from alembic import op

revision = "024o_storage_quotas"
down_revision = "024n_documents_scan_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS storage_quotas (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            scope VARCHAR(16) NOT NULL,
            scope_ref_id BIGINT DEFAULT 0,
            used_bytes BIGINT DEFAULT 0,
            quota_bytes BIGINT NOT NULL,
            last_recalculated_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT clock_timestamp(),
            updated_at TIMESTAMPTZ DEFAULT clock_timestamp()
        );
        ALTER TABLE storage_quotas ALTER COLUMN scope_ref_id SET DEFAULT 0;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_storage_quota_scope
            ON storage_quotas (tenant_id, scope, scope_ref_id);
    """)


def downgrade() -> None:
    op.drop_table("storage_quotas")

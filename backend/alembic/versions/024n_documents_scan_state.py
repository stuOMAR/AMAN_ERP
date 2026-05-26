"""Documents scan state extension.

Feature 024 — T068. Adds state, quarantine_path, scan fields to documents.
"""
from alembic import op

revision = "024n_documents_scan_state"
down_revision = "024m_dms_attachment_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS state VARCHAR(16) DEFAULT 'clean';
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS quarantine_path VARCHAR(1024);
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS scanned_at TIMESTAMPTZ;
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS scan_engine VARCHAR(64);
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS scan_engine_version VARCHAR(64);
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS checksum_sha256 CHAR(64);
        CREATE INDEX IF NOT EXISTS ix_docs_state ON documents (state);
    """)


def downgrade() -> None:
    op.drop_index("ix_docs_state", table_name="documents")
    for col in ["checksum_sha256", "scan_engine_version", "scan_engine", "scanned_at", "quarantine_path", "state"]:
        op.drop_column("documents", col)

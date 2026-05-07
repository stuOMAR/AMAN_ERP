"""Documents scan state extension.

Feature 024 — T068. Adds state, quarantine_path, scan fields to documents.
"""
from alembic import op
import sqlalchemy as sa

revision = "024n_documents_scan_state"
down_revision = "024m_dms_attachment_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("state", sa.String(16), server_default="clean"))
    op.add_column("documents", sa.Column("quarantine_path", sa.String(1024), nullable=True))
    op.add_column("documents", sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("scan_engine", sa.String(64), nullable=True))
    op.add_column("documents", sa.Column("scan_engine_version", sa.String(64), nullable=True))
    op.add_column("documents", sa.Column("checksum_sha256", sa.CHAR(64), nullable=True))
    op.create_index("ix_docs_state", "documents", ["state"])


def downgrade() -> None:
    op.drop_index("ix_docs_state", table_name="documents")
    for col in ["checksum_sha256", "scan_engine_version", "scan_engine", "scanned_at", "quarantine_path", "state"]:
        op.drop_column("documents", col)

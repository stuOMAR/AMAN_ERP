"""Add bank statement match uniqueness guard.

Revision: 0031_bank_statement_match_unique
Revises: 0030_audit_h_ddl_sync
Create Date: 2026-05-19
"""
from alembic import op


revision = "0031_bank_statement_match_unique"
down_revision = "0030_audit_h_ddl_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_bsl_matched_journal_line
            ON bank_statement_lines (matched_journal_line_id)
            WHERE matched_journal_line_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS uq_bsl_matched_journal_line;
        """
    )

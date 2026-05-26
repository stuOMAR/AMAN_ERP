"""T3.13: expense reversal columns

Adds the bookkeeping columns needed by ``POST /expenses/{id}/reverse`` so
a reversal can be persisted without losing the original record:

* ``reversal_journal_entry_id`` — the JE that posts the reversal.
* ``reversed_at`` / ``reversed_by`` — audit metadata.
* ``reversal_reason`` — free-text explanation.

The ``approval_status`` column already accepts arbitrary VARCHAR(20),
so the new ``reversed`` status doesn't need a schema change — only a
code-side update of ``VALID_APPROVAL_STATUSES``.

Revision ID: 0018_expense_reversal_columns
Revises: 0017_audit_logs_hash_chain_immutability
Create Date: 2026-05-01
"""
from alembic import op


revision = "0018_expense_reversal_columns"
down_revision = "0017_audit_logs_hash_chain_immutability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE expenses
            ADD COLUMN IF NOT EXISTS reversal_journal_entry_id INTEGER REFERENCES journal_entries(id),
            ADD COLUMN IF NOT EXISTS reversed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS reversed_by INTEGER REFERENCES company_users(id),
            ADD COLUMN IF NOT EXISTS reversal_reason TEXT;
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_expenses_reversal_je "
        "ON expenses(reversal_journal_entry_id) "
        "WHERE reversal_journal_entry_id IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_expenses_reversal_je;")
    op.execute("""
        ALTER TABLE expenses
            DROP COLUMN IF EXISTS reversal_reason,
            DROP COLUMN IF EXISTS reversed_by,
            DROP COLUMN IF EXISTS reversed_at,
            DROP COLUMN IF EXISTS reversal_journal_entry_id;
    """)

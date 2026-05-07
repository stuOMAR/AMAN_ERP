"""022d: Recurring template review fields + pending-review table.

Revision: 022d_recurring_template_review
Revises: 022f_treasury_balance_trigger
Create Date: 2026-05-02

Adds ``review_threshold``, ``auto_approve``, and ``expense_category_id``
to ``recurring_journal_templates``.  Creates ``recurring_je_pending_review``
for runs that exceed the threshold and require manual approval before
posting.
"""
from alembic import op


revision = "022d_recurring_template_review"
down_revision = "022f_treasury_balance_trigger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- 1. New columns on recurring_journal_templates
        ALTER TABLE recurring_journal_templates
            ADD COLUMN IF NOT EXISTS review_threshold  NUMERIC(18,4);

        ALTER TABLE recurring_journal_templates
            ADD COLUMN IF NOT EXISTS auto_approve BOOLEAN NOT NULL DEFAULT false;

        ALTER TABLE recurring_journal_templates
            ADD COLUMN IF NOT EXISTS expense_category_id BIGINT;

        -- 2. Pending-review table
        CREATE TABLE IF NOT EXISTS recurring_je_pending_review (
            id                  BIGSERIAL     PRIMARY KEY,
            tenant_id           BIGINT        NOT NULL,
            template_id         BIGINT        NOT NULL
                                REFERENCES recurring_journal_templates(id) ON DELETE CASCADE,
            run_date            DATE          NOT NULL,
            amount              NUMERIC(18,4) NOT NULL,
            expense_category_id BIGINT,
            lines               JSONB         NOT NULL DEFAULT '[]',
            status              VARCHAR(16)   NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','approved','rejected','posted')),
            journal_entry_id    BIGINT,
            approved_by         BIGINT,
            approved_at         TIMESTAMPTZ,
            rejected_by         BIGINT,
            rejected_at         TIMESTAMPTZ,
            rejection_reason    TEXT,
            created_at          TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp(),
            updated_at          TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp()
        );

        CREATE INDEX IF NOT EXISTS ix_recurring_review_tenant_status
            ON recurring_je_pending_review (tenant_id, status);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS recurring_je_pending_review;

        ALTER TABLE recurring_journal_templates
            DROP COLUMN IF EXISTS expense_category_id;
        ALTER TABLE recurring_journal_templates
            DROP COLUMN IF EXISTS auto_approve;
        ALTER TABLE recurring_journal_templates
            DROP COLUMN IF EXISTS review_threshold;
        """
    )

"""approvals: add idempotency key for approval actions

Revision ID: 031f_approvals_workflow_security_authority
Revises: 031e_reports_analytics_mvs
Create Date: 2026-05-25
"""

from typing import Union

from alembic import op


revision: str = "031f_approvals_workflow_security_authority"
down_revision: Union[str, None] = "031e_reports_analytics_mvs"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE approval_actions
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120);

        CREATE UNIQUE INDEX IF NOT EXISTS uq_approval_actions_idempotency
            ON approval_actions(idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS uq_approval_actions_idempotency;

        ALTER TABLE approval_actions
            DROP COLUMN IF EXISTS idempotency_key;
        """
    )

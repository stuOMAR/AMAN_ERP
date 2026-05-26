"""audit_logs: remove branch_id foreign key constraint

Revision ID: 030l_audit_logs_branch_id_fk_remove
Revises: 030k_bom_idempotency
Create Date: 2026-05-24

Removes the foreign key constraint from audit_logs(branch_id) to branches(id).
This ensures audit logs are truly robust and historic, preventing failures when
referenced branches are deleted, or when the asynchronous outbox worker flushes
actions associated with deleted branches.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "030l_audit_logs_branch_id_fk_remove"
down_revision: Union[str, None] = "030k_bom_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drops the foreign key constraint on branch_id if it exists
    op.execute("ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_branch_id_fkey")


def downgrade() -> None:
    # Restores the foreign key constraint
    op.execute("ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_branch_id_fkey FOREIGN KEY (branch_id) REFERENCES branches(id)")

"""merge heads 0034 and 030g

Revision ID: 0035_merge_heads
Revises: 0034_payroll_period_overlap_constraint, 030g_projects_expenses_time_idempotency
Create Date: 2026-05-21 18:00:00.000000
"""
from typing import Sequence, Union

# revision identifiers
revision: str = '0035_merge_heads'
down_revision: Union[str, None] = ('0034_payroll_period_overlap_constraint', '030g_projects_expenses_time_idempotency')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

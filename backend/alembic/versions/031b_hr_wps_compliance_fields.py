"""hr: add WPS labor compliance fields

Revision ID: 031b_hr_wps_compliance_fields
Revises: 031a_hr_idempotency_keys
Create Date: 2026-05-24

Adds employee fields required for Saudi WPS compliance checks where they are
applicable to non-Saudi workers.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "031b_hr_wps_compliance_fields"
down_revision: Union[str, None] = "031a_hr_idempotency_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS labor_card_number VARCHAR(50)")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS insurance_number VARCHAR(50)")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS visa_status VARCHAR(50)")


def downgrade() -> None:
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS visa_status")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS insurance_number")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS labor_card_number")

"""Add service pricing fields.

Revision: 0024_service_pricing_fields
Revises: 0023_archive_tables
Create Date: 2026-05-01

Adds the service request hourly rate and service cost markup percentage
columns used by the services API schemas.
"""
from alembic import op


revision = "0024_service_pricing_fields"
down_revision = "0023_archive_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE service_requests
            ADD COLUMN IF NOT EXISTS hourly_rate NUMERIC(15, 4);

        ALTER TABLE service_request_costs
            ADD COLUMN IF NOT EXISTS markup_pct NUMERIC(8, 4) DEFAULT 0;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE service_request_costs
            DROP COLUMN IF EXISTS markup_pct;

        ALTER TABLE service_requests
            DROP COLUMN IF EXISTS hourly_rate;
        """
    )
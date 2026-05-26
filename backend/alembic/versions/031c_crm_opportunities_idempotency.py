"""crm: add idempotency keys to opportunities and campaigns

Revision ID: 031c_crm_opportunities_idempotency
Revises: 031b_hr_wps_compliance_fields
Create Date: 2026-05-25
"""

from typing import Union

from alembic import op


revision: str = "031c_crm_opportunities_idempotency"
down_revision: Union[str, None] = "031b_hr_wps_compliance_fields"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE sales_opportunities
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_opportunities_idempotency
        ON sales_opportunities (idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE marketing_campaigns
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_marketing_campaigns_idempotency
        ON marketing_campaigns (idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE marketing_campaigns
        ADD COLUMN IF NOT EXISTS execution_idempotency_key VARCHAR(120)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_marketing_campaigns_execution_idempotency
        ON marketing_campaigns (execution_idempotency_key)
        WHERE execution_idempotency_key IS NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE campaign_lead_attributions
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_campaign_lead_attr_idempotency
        ON campaign_lead_attributions (idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_campaign_lead_attr_campaign_lead
        ON campaign_lead_attributions (campaign_id, lead_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_campaign_lead_attr_campaign_lead")
    op.execute("DROP INDEX IF EXISTS uq_campaign_lead_attr_idempotency")
    op.execute("ALTER TABLE campaign_lead_attributions DROP COLUMN IF EXISTS idempotency_key")
    op.execute("DROP INDEX IF EXISTS uq_marketing_campaigns_execution_idempotency")
    op.execute("ALTER TABLE marketing_campaigns DROP COLUMN IF EXISTS execution_idempotency_key")
    op.execute("DROP INDEX IF EXISTS uq_marketing_campaigns_idempotency")
    op.execute("ALTER TABLE marketing_campaigns DROP COLUMN IF EXISTS idempotency_key")
    op.execute("DROP INDEX IF EXISTS uq_sales_opportunities_idempotency")
    op.execute("ALTER TABLE sales_opportunities DROP COLUMN IF EXISTS idempotency_key")

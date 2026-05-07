"""Service contracts extension.

Feature 024 — T045. Adds coverage_rules, pricing_strategy, maintenance_schedule, renew_policy.
"""
from alembic import op
import sqlalchemy as sa

revision = "024i_service_contracts_extension"
down_revision = "024h_service_pricelists"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service_contracts", sa.Column("coverage_rules", sa.JSON(), nullable=True))
    op.add_column("service_contracts", sa.Column("pricing_strategy", sa.String(32), nullable=True))
    op.add_column("service_contracts", sa.Column("maintenance_schedule", sa.JSON(), nullable=True))
    op.add_column("service_contracts", sa.Column("renew_policy", sa.String(32), nullable=True))
    op.add_column("service_contracts", sa.Column("auto_renewed_to_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_svc_contract_auto_renewed", "service_contracts", "service_contracts", ["auto_renewed_to_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_svc_contract_auto_renewed", "service_contracts", type_="foreignkey")
    for col in ["auto_renewed_to_id", "renew_policy", "maintenance_schedule", "pricing_strategy", "coverage_rules"]:
        op.drop_column("service_contracts", col)

"""add updated_at to project and asset tables

Revision ID: 0004_add_updated_at_columns
Revises: 0003_add_project_retainer_columns
Create Date: 2026-04-20

Add updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP to 15 tables that were
missing it, per Constitution XVII (all tables must have updated_at).

Tables: project_tasks, project_budgets, project_expenses, project_revenues,
project_documents, asset_depreciation_schedule, asset_transfers,
asset_revaluations, asset_insurance, asset_maintenance, contract_items,
task_dependencies, lease_contracts, asset_impairments, contract_amendments.

Constitution XXVIII: Applied together with database.py CREATE TABLE update.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0004_add_updated_at_columns"
down_revision = "0003_add_project_retainer_columns"
branch_labels = None
depends_on = None

_TABLES = [
    "project_tasks",
    "project_budgets",
    "project_expenses",
    "project_revenues",
    "project_documents",
    "asset_depreciation_schedule",
    "asset_transfers",
    "asset_revaluations",
    "asset_insurance",
    "asset_maintenance",
    "contract_items",
    "task_dependencies",
    "lease_contracts",
    "asset_impairments",
    "contract_amendments",
]


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()
    for table in _TABLES:
        if table in existing_tables:
            columns = [c["name"] for c in inspector.get_columns(table)]
            if "updated_at" not in columns:
                op.add_column(
                    table,
                    sa.Column(
                        "updated_at",
                        sa.DateTime(timezone=True),
                        server_default=sa.text("CURRENT_TIMESTAMP"),
                        nullable=True,
                    ),
                )


def downgrade():
    for table in _TABLES:
        op.drop_column(table, "updated_at")

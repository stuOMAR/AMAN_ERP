"""031i: permissions audit hardening

Revision ID: 031i_permissions_audit_hardening
Revises: 031h_search_query_logs_and_tenant_types
"""
from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "031i_permissions_audit_hardening"
down_revision: Union[str, None] = "031h_search_query_logs_and_tenant_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_field_permissions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL REFERENCES company_users(id) ON DELETE CASCADE,
            field_restrictions JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS role_field_permissions (
            id SERIAL PRIMARY KEY,
            role_name VARCHAR(50) UNIQUE NOT NULL REFERENCES roles(role_name) ON DELETE CASCADE,
            field_restrictions JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_warehouses (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES company_users(id) ON DELETE CASCADE,
            warehouse_id INTEGER NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, warehouse_id)
        );

        CREATE TABLE IF NOT EXISTS user_cost_centers (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES company_users(id) ON DELETE CASCADE,
            cost_center_id INTEGER NOT NULL REFERENCES cost_centers(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, cost_center_id)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS user_cost_centers;
        DROP TABLE IF EXISTS user_warehouses;
        DROP TABLE IF EXISTS role_field_permissions;
        DROP TABLE IF EXISTS user_field_permissions;
        """
    )

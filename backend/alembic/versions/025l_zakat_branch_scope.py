"""025l — zakat branch scope collision fix

Revision ID: 025l_zakat_branch_scope
Revises: 025k_tax_compliance_hardening
Create Date: 2026-05-09
"""
from alembic import op
import sqlalchemy as sa

revision = "025l_zakat_branch_scope"
down_revision = "025k_tax_compliance_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "zakat_calculations",
        sa.Column("branch_scope_key", sa.String(160), nullable=True),
    )
    op.add_column(
        "zakat_calculations",
        sa.Column("branch_ids", sa.JSON(), nullable=True),
    )

    # Backfill existing rows
    op.execute("""
        UPDATE zakat_calculations
        SET branch_scope_key = CASE
            WHEN branch_id IS NOT NULL THEN 'branch:' || branch_id::text
            ELSE 'all:company'
        END
        WHERE branch_scope_key IS NULL
    """)

    op.alter_column(
        "zakat_calculations",
        "branch_scope_key",
        nullable=False,
        existing_nullable=True,
    )

    # Drop the old scope index from 025k before creating the replacement.
    op.execute("DROP INDEX IF EXISTS uq_zakat_calculations_year_branch")

    # New unique index
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_zakat_calculations_year_scope
            ON zakat_calculations (fiscal_year, branch_scope_key)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_zakat_calculations_year_scope")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_zakat_calculations_year_branch
            ON zakat_calculations (fiscal_year, COALESCE(branch_id, 0))
    """)
    op.drop_column("zakat_calculations", "branch_ids")
    op.drop_column("zakat_calculations", "branch_scope_key")

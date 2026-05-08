"""025j: Add branch_id column to customer_price_lists.

Revision: 025j_customer_price_lists_branch
Revises: 025i_journal_lines_txn_currency
Create Date: 2026-05-08

Adds the branch_id to customer_price_lists to support branch-specific price list filtering in the frontend.
"""
from alembic import op


revision = "025j_customer_price_lists_branch"
down_revision = "025i_journal_lines_txn_currency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.customer_price_lists') IS NOT NULL THEN
                ALTER TABLE customer_price_lists
                    ADD COLUMN IF NOT EXISTS branch_id INTEGER;

                IF to_regclass('public.branches') IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1
                         FROM pg_constraint
                        WHERE conname = 'fk_customer_price_lists_branch_id'
                          AND conrelid = 'public.customer_price_lists'::regclass
                   ) THEN
                    ALTER TABLE customer_price_lists
                        ADD CONSTRAINT fk_customer_price_lists_branch_id
                        FOREIGN KEY (branch_id) REFERENCES branches(id)
                        ON DELETE SET NULL;
                END IF;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.customer_price_lists') IS NOT NULL THEN
                ALTER TABLE customer_price_lists DROP CONSTRAINT IF EXISTS fk_customer_price_lists_branch_id;
                ALTER TABLE customer_price_lists DROP COLUMN IF EXISTS branch_id;
            END IF;
        END $$;
        """
    )

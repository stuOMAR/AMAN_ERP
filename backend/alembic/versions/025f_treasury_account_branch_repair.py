"""025f: Repair treasury account branch linkage columns.

Revision: 025f_treasury_branch_repair
Revises: 025e_audit_text_tenant_repair
Create Date: 2026-05-04

Older tenant databases may miss the branch linkage and overdraft flag columns
used by the treasury account UI. The canonical schema has these columns; this
migration makes existing companies match it without changing existing account
assignments.
"""
from alembic import op


revision = "025f_treasury_branch_repair"
down_revision = "025e_audit_text_tenant_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.treasury_accounts') IS NOT NULL THEN
                ALTER TABLE treasury_accounts
                    ADD COLUMN IF NOT EXISTS branch_id INTEGER,
                    ADD COLUMN IF NOT EXISTS allow_overdraft BOOLEAN;

                UPDATE treasury_accounts
                   SET allow_overdraft = FALSE
                 WHERE allow_overdraft IS NULL;

                                IF to_regclass('public.branches') IS NOT NULL THEN
                                        UPDATE treasury_accounts ta
                                             SET branch_id = NULL
                                         WHERE branch_id IS NOT NULL
                                             AND NOT EXISTS (
                                                     SELECT 1 FROM branches b WHERE b.id = ta.branch_id
                                             );
                                END IF;

                ALTER TABLE treasury_accounts
                    ALTER COLUMN allow_overdraft SET DEFAULT FALSE,
                    ALTER COLUMN allow_overdraft SET NOT NULL;

                CREATE INDEX IF NOT EXISTS idx_treasury_accounts_branch_active
                    ON treasury_accounts (branch_id, is_active);

                IF to_regclass('public.branches') IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1
                         FROM pg_constraint
                        WHERE conname = 'fk_treasury_accounts_branch_id'
                          AND conrelid = 'public.treasury_accounts'::regclass
                   ) THEN
                    ALTER TABLE treasury_accounts
                        ADD CONSTRAINT fk_treasury_accounts_branch_id
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
            IF to_regclass('public.treasury_accounts') IS NOT NULL THEN
                ALTER TABLE treasury_accounts
                    ALTER COLUMN allow_overdraft DROP NOT NULL,
                    ALTER COLUMN allow_overdraft SET DEFAULT NULL;
            END IF;
        END $$;
        """
    )
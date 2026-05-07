"""Loans/advances account mapping split.

Feature 024 — T031. Creates acc_map_loans and acc_map_advances tables.
"""
from alembic import op
import sqlalchemy as sa

revision = "024e_acc_map_loans_advances_split"
down_revision = "024d_payslip_uniqueness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("acc_map_loans", "acc_map_advances"):
        op.create_table(
            table,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.BigInteger(), nullable=False),
            sa.Column("debit_account_id", sa.BigInteger(), nullable=False),
            sa.Column("credit_account_id", sa.BigInteger(), nullable=False),
            sa.Column("valid_from", sa.Date(), nullable=False),
            sa.Column("valid_to", sa.Date(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
        )
        op.create_index(f"ix_{table}_tenant", table, ["tenant_id"])

    # Backfill from existing acc_map_loans_adv if it exists
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'acc_map_loans_adv') THEN
                INSERT INTO acc_map_loans (tenant_id, debit_account_id, credit_account_id, valid_from, valid_to)
                SELECT tenant_id, debit_account_id, credit_account_id, valid_from, valid_to FROM acc_map_loans_adv;
                INSERT INTO acc_map_advances (tenant_id, debit_account_id, credit_account_id, valid_from, valid_to)
                SELECT tenant_id, debit_account_id, credit_account_id, valid_from, valid_to FROM acc_map_loans_adv;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_table("acc_map_advances")
    op.drop_table("acc_map_loans")

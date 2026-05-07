"""HR PII encryption columns.

Feature 024 — T005. Adds BYTEA columns for encrypted PII fields,
salary_currency, ticket_allowance columns, bank_code_id, technician_profile_id.
"""
from alembic import op
import sqlalchemy as sa

revision = "024a_hr_pii_encryption"
down_revision = "023m_inventory_transactions_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Employees: add encrypted BYTEA columns (data-preserving; actual encryption in T015)
    op.add_column("employees", sa.Column("salary_encrypted", sa.LargeBinary(), nullable=True))
    op.add_column("employees", sa.Column("iban_encrypted", sa.LargeBinary(), nullable=True))
    op.add_column("employees", sa.Column("national_id_encrypted", sa.LargeBinary(), nullable=True))
    op.add_column("employees", sa.Column("passport_number_encrypted", sa.LargeBinary(), nullable=True))
    op.add_column("employees", sa.Column("bank_account_number_encrypted", sa.LargeBinary(), nullable=True))
    op.add_column("employees", sa.Column("gosi_number_encrypted", sa.LargeBinary(), nullable=True))

    # Salary currency
    op.add_column("employees", sa.Column("salary_currency", sa.CHAR(3), nullable=True))

    # Ticket allowance
    op.add_column("employees", sa.Column("ticket_allowance_amount", sa.Numeric(18, 4), nullable=True))
    op.add_column("employees", sa.Column("ticket_allowance_currency", sa.CHAR(3), nullable=True))
    op.add_column("employees", sa.Column("ticket_allowance_frequency_months", sa.SmallInteger(), server_default="12", nullable=True))
    op.add_column("employees", sa.Column("ticket_allowance_last_paid_at", sa.Date(), nullable=True))

    # FK references
    op.add_column("employees", sa.Column("bank_code_id", sa.BigInteger(), nullable=True))
    op.add_column("employees", sa.Column("technician_profile_id", sa.BigInteger(), nullable=True))

    # Employee salary history table
    op.create_table(
        "employee_salary_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("employee_id", sa.BigInteger(), nullable=False),
        sa.Column("salary_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("salary_currency", sa.CHAR(3), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("change_reason", sa.String(64), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp()),
    )
    op.create_index("ix_salary_hist_tenant_emp", "employee_salary_history", ["tenant_id", "employee_id"])


def downgrade() -> None:
    op.drop_table("employee_salary_history")
    for col in [
        "technician_profile_id", "bank_code_id",
        "ticket_allowance_last_paid_at", "ticket_allowance_frequency_months",
        "ticket_allowance_currency", "ticket_allowance_amount", "salary_currency",
        "gosi_number_encrypted", "bank_account_number_encrypted",
        "passport_number_encrypted", "national_id_encrypted",
        "iban_encrypted", "salary_encrypted",
    ]:
        op.drop_column("employees", col)

"""022e: Employee receipt settlements table.

Revision: 022e_employee_receipt_settlements
Revises: 022d_recurring_template_review
Create Date: 2026-05-02

Creates ``employee_receipt_settlements`` which wires employee receipts
against advances with approval workflow and GL posting link.

State machine: draft → submitted → approved → posted; submitted → rejected → draft.
"""
from alembic import op


revision = "022e_employee_receipt_settlements"
down_revision = "022d_recurring_template_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_receipt_settlements (
            id              BIGSERIAL     PRIMARY KEY,
            tenant_id       BIGINT        NOT NULL,
            employee_id     BIGINT        NOT NULL,
            advance_id      BIGINT        NOT NULL,
            receipt_id      BIGINT        NOT NULL,
            amount          NUMERIC(18,4) NOT NULL,
            status          VARCHAR(16)   NOT NULL DEFAULT 'draft'
                            CHECK (status IN (
                                'draft','submitted','approved','rejected','posted'
                            )),
            approved_by     BIGINT,
            je_id           BIGINT
                            REFERENCES journal_entries(id) ON DELETE SET NULL,
            created_at      TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp(),
            updated_at      TIMESTAMPTZ   NOT NULL DEFAULT clock_timestamp()
        );

        CREATE INDEX IF NOT EXISTS ix_ers_tenant_employee
            ON employee_receipt_settlements (tenant_id, employee_id);

        CREATE INDEX IF NOT EXISTS ix_ers_tenant_advance
            ON employee_receipt_settlements (tenant_id, advance_id);

        CREATE INDEX IF NOT EXISTS ix_ers_tenant_status
            ON employee_receipt_settlements (tenant_id, status);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS employee_receipt_settlements;
        """
    )

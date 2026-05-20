"""procurement idempotency guards

Revision ID: 030e_procurement_idempotency_guards
Revises: 030d_treasury_audit_integration_fixes
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op


revision: str = "030e_procurement_idempotency_guards"
down_revision: Union[str, None] = "030d_treasury_audit_integration_fixes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE payment_vouchers
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_vouchers_idempotency_key
        ON payment_vouchers (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)

    op.execute("""
        ALTER TABLE po_receipts
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_po_receipts_idempotency_key
        ON po_receipts (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)

    op.execute("""
        ALTER TABLE blanket_po_release_orders
        ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_blanket_po_release_idempotency_key
        ON blanket_po_release_orders (idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_payment_vouchers_supplier_branch_date
        ON payment_vouchers (party_type, party_id, branch_id, voucher_date)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_po_receipts_po_warehouse_date
        ON po_receipts (po_id, warehouse_id, receipt_date)
    """)
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_ap_aging")
    op.execute("""
        CREATE MATERIALIZED VIEW mv_ap_aging AS
        SELECT party_id,
               SUM(CASE WHEN NOW() - due_date <= INTERVAL '30 days' THEN amount_base ELSE 0 END) AS current_bucket,
               SUM(CASE WHEN NOW() - due_date >  INTERVAL '30 days' AND NOW() - due_date <= INTERVAL '60 days' THEN amount_base ELSE 0 END) AS bucket_30,
               SUM(CASE WHEN NOW() - due_date >  INTERVAL '60 days' AND NOW() - due_date <= INTERVAL '90 days' THEN amount_base ELSE 0 END) AS bucket_60,
               SUM(CASE WHEN NOW() - due_date >  INTERVAL '90 days' THEN amount_base ELSE 0 END) AS bucket_90_plus
        FROM (
            SELECT party_id,
                   COALESCE(due_date, invoice_date) AS due_date,
                   (total - COALESCE(paid_amount,0)) * COALESCE(exchange_rate,1) AS amount_base
            FROM invoices
            WHERE invoice_type IN ('purchase', 'purchase_debit_note')
              AND status NOT IN ('draft', 'cancelled', 'paid')
              AND (total - COALESCE(paid_amount,0)) > 0.01
            UNION ALL
            SELECT party_id,
                   invoice_date AS due_date,
                   -1 * total * COALESCE(exchange_rate,1) AS amount_base
            FROM invoices
            WHERE invoice_type IN ('purchase_credit_note', 'purchase_return')
              AND status NOT IN ('draft', 'cancelled')
        ) ap_docs
        GROUP BY party_id
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_ap_aging_party ON mv_ap_aging(party_id)")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_ap_aging")
    op.execute("""
        CREATE MATERIALIZED VIEW mv_ap_aging AS
        SELECT party_id,
               SUM(CASE WHEN NOW() - due_date <= INTERVAL '30 days' THEN (total - COALESCE(paid_amount,0)) ELSE 0 END) AS current_bucket,
               SUM(CASE WHEN NOW() - due_date >  INTERVAL '30 days' AND NOW() - due_date <= INTERVAL '60 days' THEN (total - COALESCE(paid_amount,0)) ELSE 0 END) AS bucket_30,
               SUM(CASE WHEN NOW() - due_date >  INTERVAL '60 days' AND NOW() - due_date <= INTERVAL '90 days' THEN (total - COALESCE(paid_amount,0)) ELSE 0 END) AS bucket_60,
               SUM(CASE WHEN NOW() - due_date >  INTERVAL '90 days' THEN (total - COALESCE(paid_amount,0)) ELSE 0 END) AS bucket_90_plus
        FROM invoices
        WHERE invoice_type = 'purchase' AND status IN ('posted', 'partially_paid')
        GROUP BY party_id
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_ap_aging_party ON mv_ap_aging(party_id)")
    op.execute("DROP INDEX IF EXISTS idx_po_receipts_po_warehouse_date")
    op.execute("DROP INDEX IF EXISTS idx_payment_vouchers_supplier_branch_date")
    op.execute("DROP INDEX IF EXISTS uq_blanket_po_release_idempotency_key")
    op.execute("ALTER TABLE blanket_po_release_orders DROP COLUMN IF EXISTS idempotency_key")
    op.execute("DROP INDEX IF EXISTS uq_po_receipts_idempotency_key")
    op.execute("ALTER TABLE po_receipts DROP COLUMN IF EXISTS idempotency_key")
    op.execute("DROP INDEX IF EXISTS uq_payment_vouchers_idempotency_key")
    op.execute("ALTER TABLE payment_vouchers DROP COLUMN IF EXISTS idempotency_key")

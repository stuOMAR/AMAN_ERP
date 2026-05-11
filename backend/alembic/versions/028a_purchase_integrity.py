"""028 purchase lifecycle integrity — schema changes

Revision ID: 028a_purchase_integrity
Revises: 025l_zakat_branch_scope
Create Date: 2026-05-10
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '028a_purchase_integrity'
down_revision = '025l_zakat_branch_scope'
branch_labels = None
depends_on = None


def upgrade():
    # T002: Add po_line_id to invoice_lines (PO-line-to-invoice-line linkage)
    op.execute("""
        ALTER TABLE invoice_lines
        ADD COLUMN IF NOT EXISTS po_line_id INTEGER
        REFERENCES purchase_order_lines(id) ON DELETE SET NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_invoice_lines_po_line_id
        ON invoice_lines(po_line_id)
    """)

    # T003: Add invoiced_quantity to purchase_order_lines (cumulative invoiced tracking)
    op.execute("""
        ALTER TABLE purchase_order_lines
        ADD COLUMN IF NOT EXISTS invoiced_quantity DECIMAL(18, 4) DEFAULT 0
    """)
    op.execute("""
        UPDATE purchase_order_lines
        SET invoiced_quantity = 0
        WHERE invoiced_quantity IS NULL
    """)

    # Phase 2: Create po_receipts table for receipt-level tracking (GRNI uniqueness)
    op.execute("""
        CREATE TABLE IF NOT EXISTS po_receipts (
            id SERIAL PRIMARY KEY,
            po_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
            warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            receipt_date DATE NOT NULL DEFAULT CURRENT_DATE,
            created_by INTEGER REFERENCES company_users(id),
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS po_receipt_lines (
            id SERIAL PRIMARY KEY,
            receipt_id INTEGER NOT NULL REFERENCES po_receipts(id) ON DELETE CASCADE,
            po_line_id INTEGER NOT NULL REFERENCES purchase_order_lines(id) ON DELETE RESTRICT,
            product_id INTEGER REFERENCES products(id),
            warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            quantity DECIMAL(18, 4) NOT NULL,
            unit_cost DECIMAL(18, 4) NOT NULL DEFAULT 0,
            total_cost DECIMAL(18, 4) NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_po_receipt_lines_po_line_id
        ON po_receipt_lines(po_line_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_po_receipt_lines_receipt_id
        ON po_receipt_lines(receipt_id)
    """)
    op.execute("""
        ALTER TABLE landed_costs
        ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(18, 6) DEFAULT 1
    """)

    # T045: Create RFQ supplier invitations table
    op.execute("""
        CREATE TABLE IF NOT EXISTS rfq_suppliers (
            id SERIAL PRIMARY KEY,
            rfq_id INTEGER NOT NULL REFERENCES request_for_quotations(id) ON DELETE CASCADE,
            party_id INTEGER NOT NULL REFERENCES parties(id),
            status VARCHAR(20) DEFAULT 'invited',
            invited_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            responded_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS rfq_response_lines (
            id SERIAL PRIMARY KEY,
            response_id INTEGER NOT NULL REFERENCES rfq_responses(id) ON DELETE CASCADE,
            rfq_line_id INTEGER NOT NULL REFERENCES rfq_lines(id) ON DELETE CASCADE,
            unit_price NUMERIC(15, 4) NOT NULL DEFAULT 0,
            total_price NUMERIC(15, 4) NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(response_id, rfq_line_id)
        )
    """)

    # T006: Create supplier_subledger view for AP reporting
    op.execute("""
        CREATE OR REPLACE VIEW supplier_subledger AS
        -- Purchase invoices (credit: decreases what we owe)
        SELECT
            i.party_id,
            i.branch_id,
            i.currency,
            'purchase_invoice' AS document_type,
            i.id AS document_id,
            i.invoice_number AS document_number,
            i.invoice_date AS document_date,
            0 AS debit,
            i.total AS credit,
            0 AS base_debit,
            (i.total * COALESCE(i.exchange_rate, 1)) AS base_credit,
            COALESCE(i.exchange_rate, 1) AS exchange_rate
        FROM invoices i
        WHERE i.invoice_type = 'purchase'
          AND i.status NOT IN ('draft', 'cancelled')

        UNION ALL

        -- Purchase returns (debit: increases what we owe)
        SELECT
            i.party_id,
            i.branch_id,
            i.currency,
            'purchase_return' AS document_type,
            i.id AS document_id,
            i.invoice_number AS document_number,
            i.invoice_date AS document_date,
            i.total AS debit,
            0 AS credit,
            (i.total * COALESCE(i.exchange_rate, 1)) AS base_debit,
            0 AS base_credit,
            COALESCE(i.exchange_rate, 1) AS exchange_rate
        FROM invoices i
        WHERE i.invoice_type = 'purchase_return'
          AND i.status NOT IN ('draft', 'cancelled')

        UNION ALL

        -- Supplier payments (debit: reduces what we owe)
        SELECT
            pv.party_id,
            pv.branch_id,
            pv.currency,
            'payment' AS document_type,
            pv.id AS document_id,
            pv.voucher_number AS document_number,
            pv.voucher_date AS document_date,
            pv.amount AS debit,
            0 AS credit,
            (pv.amount * COALESCE(pv.exchange_rate, 1)) AS base_debit,
            0 AS base_credit,
            COALESCE(pv.exchange_rate, 1) AS exchange_rate
        FROM payment_vouchers pv
        WHERE pv.voucher_type = 'payment'
          AND pv.status NOT IN ('draft', 'cancelled')

        UNION ALL

        -- Supplier refunds (credit: cash refund settles supplier debit balance)
        SELECT
            pv.party_id,
            pv.branch_id,
            pv.currency,
            'refund' AS document_type,
            pv.id AS document_id,
            pv.voucher_number AS document_number,
            pv.voucher_date AS document_date,
            0 AS debit,
            pv.amount AS credit,
            0 AS base_debit,
            (pv.amount * COALESCE(pv.exchange_rate, 1)) AS base_credit,
            COALESCE(pv.exchange_rate, 1) AS exchange_rate
        FROM payment_vouchers pv
        WHERE pv.voucher_type = 'refund'
          AND pv.status NOT IN ('draft', 'cancelled')

        UNION ALL

        -- Purchase credit/debit notes
        SELECT
            i.party_id,
            i.branch_id,
            i.currency,
            i.invoice_type AS document_type,
            i.id AS document_id,
            i.invoice_number AS document_number,
            i.invoice_date AS document_date,
            CASE WHEN i.invoice_type = 'purchase_credit_note' THEN i.total ELSE 0 END AS debit,
            CASE WHEN i.invoice_type = 'purchase_debit_note' THEN i.total ELSE 0 END AS credit,
            CASE WHEN i.invoice_type = 'purchase_credit_note' THEN (i.total * COALESCE(i.exchange_rate, 1)) ELSE 0 END AS base_debit,
            CASE WHEN i.invoice_type = 'purchase_debit_note' THEN (i.total * COALESCE(i.exchange_rate, 1)) ELSE 0 END AS base_credit,
            COALESCE(i.exchange_rate, 1) AS exchange_rate
        FROM invoices i
        WHERE i.invoice_type IN ('purchase_credit_note', 'purchase_debit_note')
          AND i.status NOT IN ('draft', 'cancelled')

        UNION ALL

        -- Vendor-issued landed costs
        SELECT
            lci.vendor_id AS party_id,
            lc.branch_id,
            COALESCE(lc.currency, 'SAR') AS currency,
            'landed_cost' AS document_type,
            lc.id AS document_id,
            lc.lc_number AS document_number,
            lc.lc_date AS document_date,
            0 AS debit,
            lci.amount AS credit,
            0 AS base_debit,
            (lci.amount * COALESCE(lc.exchange_rate, 1)) AS base_credit,
            COALESCE(lc.exchange_rate, 1) AS exchange_rate
        FROM landed_cost_items lci
        JOIN landed_costs lc ON lc.id = lci.landed_cost_id
        WHERE lci.vendor_id IS NOT NULL
          AND lc.status = 'posted'
    """)


def downgrade():
    op.execute("DROP VIEW IF EXISTS supplier_subledger")
    op.execute("DROP TABLE IF EXISTS rfq_response_lines")
    op.execute("DROP TABLE IF EXISTS po_receipt_lines")
    op.execute("DROP TABLE IF EXISTS rfq_suppliers")
    op.execute("DROP TABLE IF EXISTS po_receipts")
    op.execute("ALTER TABLE landed_costs DROP COLUMN IF EXISTS exchange_rate")
    op.execute("ALTER TABLE purchase_order_lines DROP COLUMN IF EXISTS invoiced_quantity")
    op.execute("DROP INDEX IF EXISTS idx_invoice_lines_po_line_id")
    op.execute("ALTER TABLE invoice_lines DROP COLUMN IF EXISTS po_line_id")

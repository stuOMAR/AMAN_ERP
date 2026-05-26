"""reports: align analytics materialized views with dashboard widgets

Revision ID: 031e_reports_analytics_mvs
Revises: 031d_contracts_backend_authority
Create Date: 2026-05-25
"""

from typing import Union

from alembic import op


revision: str = "031e_reports_analytics_mvs"
down_revision: Union[str, None] = "031d_contracts_backend_authority"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


DROP_ANALYTICS_MVS = """
DROP MATERIALIZED VIEW IF EXISTS mv_sales_pipeline CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_inventory_turnover CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_ap_aging CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_ar_aging CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_top_customers CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_cash_position CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_expense_summary CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_revenue_summary CASCADE;
"""


ANALYTICS_MVS = """
CREATE TABLE IF NOT EXISTS analytics_mv_freshness (
    mv_name VARCHAR(128) PRIMARY KEY,
    last_refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    refresh_duration_ms INTEGER
);

CREATE MATERIALIZED VIEW mv_revenue_summary AS
    SELECT date_trunc('month', invoice_date) AS month,
           branch_id,
           SUM(total * COALESCE(exchange_rate, 1)) AS total_revenue,
           COUNT(*) AS invoice_count
    FROM invoices
    WHERE invoice_type IN ('sales', 'sale', 'pos_invoice') AND status NOT IN ('draft', 'cancelled')
    GROUP BY date_trunc('month', invoice_date), branch_id;
CREATE UNIQUE INDEX ux_mv_revenue_month ON mv_revenue_summary(month, branch_id);

CREATE MATERIALIZED VIEW mv_expense_summary AS
    SELECT date_trunc('month', invoice_date) AS month,
           branch_id,
           SUM(total * COALESCE(exchange_rate, 1)) AS total_expenses,
           COUNT(*) AS invoice_count
    FROM invoices
    WHERE invoice_type IN ('purchase', 'purchase_invoice') AND status NOT IN ('draft', 'cancelled')
    GROUP BY date_trunc('month', invoice_date), branch_id;
CREATE UNIQUE INDEX ux_mv_expense_month ON mv_expense_summary(month, branch_id);

CREATE MATERIALIZED VIEW mv_cash_position AS
    SELECT ta.id AS account_id,
           ta.name AS account_name,
           ta.account_number,
           ta.branch_id,
           COALESCE(SUM(CASE
               WHEN tt.transaction_type IN ('deposit','receipt','transfer_in','pos_sale','income') THEN tt.amount * COALESCE(tt.exchange_rate, 1)
               WHEN tt.transaction_type IN ('withdraw','withdrawal','payment','transfer_out','expense','transfer') THEN -tt.amount * COALESCE(tt.exchange_rate, 1)
               ELSE 0
           END), 0) AS balance
    FROM treasury_accounts ta
    LEFT JOIN treasury_transactions tt
           ON tt.treasury_id = ta.id AND tt.status IN ('posted', 'completed')
    GROUP BY ta.id, ta.name, ta.account_number, ta.branch_id;
CREATE UNIQUE INDEX ux_mv_cash_account ON mv_cash_position(account_id);

CREATE MATERIALIZED VIEW mv_top_customers AS
    SELECT i.party_id,
           p.name AS customer_name,
           i.branch_id,
           COUNT(*) AS invoice_count,
           SUM(i.total * COALESCE(i.exchange_rate, 1)) AS total_amount
    FROM invoices i
    JOIN parties p ON p.id = i.party_id
    WHERE i.invoice_type IN ('sales', 'sale', 'pos_invoice') AND i.status NOT IN ('draft', 'cancelled')
    GROUP BY i.party_id, p.name, i.branch_id;
CREATE UNIQUE INDEX ux_mv_top_cust_party ON mv_top_customers(party_id, branch_id);

CREATE MATERIALIZED VIEW mv_ar_aging AS
    SELECT i.party_id,
           p.name AS customer_name,
           i.branch_id,
           SUM(CASE WHEN CURRENT_DATE - COALESCE(i.due_date, i.invoice_date) <= 30 THEN (i.total - COALESCE(i.paid_amount,0)) * COALESCE(i.exchange_rate,1) ELSE 0 END) AS current_bucket,
           SUM(CASE WHEN CURRENT_DATE - COALESCE(i.due_date, i.invoice_date) > 30 AND CURRENT_DATE - COALESCE(i.due_date, i.invoice_date) <= 60 THEN (i.total - COALESCE(i.paid_amount,0)) * COALESCE(i.exchange_rate,1) ELSE 0 END) AS days_31_60,
           SUM(CASE WHEN CURRENT_DATE - COALESCE(i.due_date, i.invoice_date) > 60 AND CURRENT_DATE - COALESCE(i.due_date, i.invoice_date) <= 90 THEN (i.total - COALESCE(i.paid_amount,0)) * COALESCE(i.exchange_rate,1) ELSE 0 END) AS days_61_90,
           SUM(CASE WHEN CURRENT_DATE - COALESCE(i.due_date, i.invoice_date) > 90 THEN (i.total - COALESCE(i.paid_amount,0)) * COALESCE(i.exchange_rate,1) ELSE 0 END) AS days_over_90
    FROM invoices i
    JOIN parties p ON p.id = i.party_id
    WHERE i.invoice_type IN ('sales', 'sale', 'pos_invoice')
      AND i.status NOT IN ('draft', 'cancelled', 'paid')
      AND (i.total - COALESCE(i.paid_amount,0)) > 0.01
    GROUP BY i.party_id, p.name, i.branch_id;
CREATE UNIQUE INDEX ux_mv_ar_aging_party ON mv_ar_aging(party_id, branch_id);

CREATE MATERIALIZED VIEW mv_ap_aging AS
    SELECT ap_docs.party_id,
           p.name AS supplier_name,
           ap_docs.branch_id,
           SUM(CASE WHEN CURRENT_DATE - due_date <= 30 THEN amount_base ELSE 0 END) AS current_bucket,
           SUM(CASE WHEN CURRENT_DATE - due_date > 30 AND CURRENT_DATE - due_date <= 60 THEN amount_base ELSE 0 END) AS days_31_60,
           SUM(CASE WHEN CURRENT_DATE - due_date > 60 AND CURRENT_DATE - due_date <= 90 THEN amount_base ELSE 0 END) AS days_61_90,
           SUM(CASE WHEN CURRENT_DATE - due_date > 90 THEN amount_base ELSE 0 END) AS days_over_90
    FROM (
        SELECT party_id,
               branch_id,
               COALESCE(due_date, invoice_date) AS due_date,
               (total - COALESCE(paid_amount,0)) * COALESCE(exchange_rate,1) AS amount_base
        FROM invoices
        WHERE invoice_type IN ('purchase', 'purchase_invoice', 'purchase_debit_note')
          AND status NOT IN ('draft', 'cancelled', 'paid')
          AND (total - COALESCE(paid_amount,0)) > 0.01
        UNION ALL
        SELECT party_id,
               branch_id,
               invoice_date AS due_date,
               -1 * total * COALESCE(exchange_rate,1) AS amount_base
        FROM invoices
        WHERE invoice_type IN ('purchase_credit_note', 'purchase_return')
          AND status NOT IN ('draft', 'cancelled')
    ) ap_docs
    JOIN parties p ON p.id = ap_docs.party_id
    GROUP BY ap_docs.party_id, p.name, ap_docs.branch_id;
CREATE UNIQUE INDEX ux_mv_ap_aging_party ON mv_ap_aging(party_id, branch_id);

CREATE MATERIALIZED VIEW mv_inventory_turnover AS
    WITH sold AS (
        SELECT it.product_id,
               w.branch_id,
               SUM(CASE WHEN it.transaction_type IN ('out', 'sale', 'sales') THEN ABS(it.quantity) ELSE 0 END) AS total_sold
        FROM inventory_transactions it
        LEFT JOIN warehouses w ON w.id = it.warehouse_id
        GROUP BY it.product_id, w.branch_id
    ),
    stock AS (
        SELECT inv.product_id,
               w.branch_id,
               SUM(inv.quantity) AS current_stock
        FROM inventory inv
        LEFT JOIN warehouses w ON w.id = inv.warehouse_id
        GROUP BY inv.product_id, w.branch_id
    ),
    keys AS (
        SELECT product_id, branch_id FROM sold
        UNION
        SELECT product_id, branch_id FROM stock
    )
    SELECT k.product_id,
           p.product_name,
           k.branch_id,
           COALESCE(s.total_sold, 0) AS total_sold,
           COALESCE(st.current_stock, 0) AS current_stock,
           CASE WHEN COALESCE(st.current_stock, 0) > 0 THEN COALESCE(s.total_sold, 0) / st.current_stock ELSE 0 END AS turnover_ratio
    FROM keys k
    JOIN products p ON p.id = k.product_id
    LEFT JOIN sold s ON s.product_id = k.product_id AND s.branch_id IS NOT DISTINCT FROM k.branch_id
    LEFT JOIN stock st ON st.product_id = k.product_id AND st.branch_id IS NOT DISTINCT FROM k.branch_id;
CREATE UNIQUE INDEX ux_mv_inv_turn_product ON mv_inventory_turnover(product_id, branch_id);

CREATE MATERIALIZED VIEW mv_sales_pipeline AS
    SELECT branch_id,
           stage,
           COUNT(*) AS deal_count,
           SUM(expected_value) AS total_value,
           AVG(probability) AS avg_probability
    FROM sales_opportunities
    GROUP BY branch_id, stage;
CREATE UNIQUE INDEX ux_mv_pipeline_stage ON mv_sales_pipeline(stage, branch_id);
"""


def upgrade() -> None:
    op.execute(DROP_ANALYTICS_MVS)
    op.execute(ANALYTICS_MVS)


def downgrade() -> None:
    op.execute(DROP_ANALYTICS_MVS)
    op.execute("DROP TABLE IF EXISTS analytics_mv_freshness")

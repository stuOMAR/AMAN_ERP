"""Centralized VAT aggregation helper for reports and returns."""
from decimal import Decimal

_D2 = Decimal("0.01")

def invoice_vat_totals_subquery(
    invoice_type_param: str,
    branch_filter: str,
    *,
    date_column: str = "i.invoice_date",
) -> str:
    """Return a subquery that aggregates at invoice level.

    Do not use SUM(DISTINCT i.tax_amount): if two invoices have the same tax
    amount, DISTINCT will understate VAT. The invoice row is the authoritative
    source after header discount and exchange-rate locking.
    """
    return f"""
        SELECT
            COALESCE(SUM(inv.taxable_amount), 0) AS taxable,
            COALESCE(SUM(inv.vat_amount), 0) AS vat
        FROM (
            SELECT
                i.id,
                ((COALESCE(i.subtotal, 0) - COALESCE(i.discount, 0)) * COALESCE(i.exchange_rate, 1)) AS taxable_amount,
                (COALESCE(i.tax_amount, 0) * COALESCE(i.exchange_rate, 1)) AS vat_amount
            FROM invoices i
            WHERE i.invoice_type = :{invoice_type_param}
              AND i.status NOT IN ('draft', 'cancelled')
              AND {date_column} >= :start
              AND {date_column} < :end
              {branch_filter}
        ) inv
    """

def adjusted_line_taxable_cte(extra_where: str) -> str:
    """Use only for boxed/rate/classification reports that must split VAT by line.

    Important: invoices.discount may include line discounts plus header discount.
    Therefore compute header-only discount as:
    GREATEST(i.discount - SUM(line_discount), 0)

    The query exposes adjusted_taxable_base. VAT for a line is then:
    adjusted_taxable_base * (tax_rate / 100)
    """
    return f"""
        WITH line_base AS (
            SELECT
                i.id AS invoice_id,
                i.invoice_type,
                i.invoice_date,
                i.branch_id,
                COALESCE(i.exchange_rate, 1) AS exchange_rate,
                COALESCE(i.discount, 0) AS invoice_discount,
                il.product_id,
                il.tax_rate,
                (COALESCE(il.quantity, 0) * COALESCE(il.unit_price, 0)) AS gross_line_base,
                COALESCE(il.discount, 0) AS line_discount,
                (COALESCE(il.quantity, 0) * COALESCE(il.unit_price, 0) - COALESCE(il.discount, 0)) AS line_taxable_before_header,
                SUM(COALESCE(il.discount, 0)) OVER (PARTITION BY i.id) AS line_discount_sum,
                SUM(COALESCE(il.quantity, 0) * COALESCE(il.unit_price, 0) - COALESCE(il.discount, 0)) OVER (PARTITION BY i.id) AS invoice_line_taxable_sum
            FROM invoices i
            JOIN invoice_lines il ON il.invoice_id = i.id
            WHERE i.status NOT IN ('draft', 'cancelled')
              {extra_where}
        ),
        adjusted_lines AS (
            SELECT *,
                GREATEST(invoice_discount - line_discount_sum, 0) AS header_discount_only,
                (
                    line_taxable_before_header
                    - CASE
                        WHEN invoice_line_taxable_sum > 0
                        THEN GREATEST(invoice_discount - line_discount_sum, 0)
                             * line_taxable_before_header / invoice_line_taxable_sum
                        ELSE 0
                      END
                ) * exchange_rate AS adjusted_taxable_base
            FROM line_base
        )
    """

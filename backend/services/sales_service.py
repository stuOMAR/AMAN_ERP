"""Unified sales totals source.

Provides a single function `get_sales_total` consumed by both the
Dashboard and the Reports pages so that the same period/branch always
yields the same headline number. See `docs/audit/TODO.md` task T3.1.

Gross sales = sales invoices (excluding cancelled/draft) + completed POS
orders, converted to base currency via the invoice exchange_rate.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional, Sequence

from sqlalchemy import text


def get_sales_total(
    db,
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    branch_ids: Optional[Sequence[int]] = None,
    include_pos: bool = True,
) -> Dict[str, Any]:
    """Return unified sales totals (base currency) for the given period.

    Args:
        db: SQLAlchemy connection / session.
        start_date: Inclusive lower bound (None = open).
        end_date: Inclusive upper bound (None = open).
        branch_id: Restrict to a single branch.
        branch_ids: Restrict to a set of allowed branches.
        include_pos: When False, only sales invoices are summed.

    Returns:
        dict with keys:
            total_sales (Decimal): gross including tax in base currency.
            invoice_count (int): number of contributing documents.
            total_paid (Decimal): collected amount in base currency.
            total_due (Decimal): max(total_sales - total_paid, 0).
    """
    params: Dict[str, Any] = {}
    inv_filters = ["invoice_type = 'sales'", "status NOT IN ('cancelled', 'draft')"]
    pos_filters = ["status IN ('paid', 'completed')"]

    if start_date is not None:
        params["start_date"] = start_date
        inv_filters.append("invoice_date >= :start_date")
        pos_filters.append("CAST(order_date AS DATE) >= :start_date")
    if end_date is not None:
        params["end_date"] = end_date
        inv_filters.append("invoice_date <= :end_date")
        pos_filters.append("CAST(order_date AS DATE) <= :end_date")
    if branch_id is not None:
        params["branch_id"] = branch_id
        inv_filters.append("branch_id = :branch_id")
        pos_filters.append("branch_id = :branch_id")
    elif branch_ids is not None:
        branch_ids = list(branch_ids)
        if branch_ids:
            params["branch_ids"] = branch_ids
            inv_filters.append("branch_id = ANY(:branch_ids)")
            pos_filters.append("branch_id = ANY(:branch_ids)")
        else:
            inv_filters.append("1=0")
            pos_filters.append("1=0")

    inv_where = " AND ".join(inv_filters)
    inv_row = db.execute(
        text(
            f"""
            SELECT
                COUNT(*) AS cnt,
                COALESCE(SUM(total * COALESCE(exchange_rate, 1.0)), 0) AS total_sales,
                COALESCE(SUM(paid_amount * COALESCE(exchange_rate, 1.0)), 0) AS total_paid
            FROM invoices
            WHERE {inv_where}
            """
        ),
        params,
    ).fetchone()

    inv_cnt = int(inv_row.cnt or 0)
    inv_sales = Decimal(str(inv_row.total_sales or 0))
    inv_paid = Decimal(str(inv_row.total_paid or 0))

    pos_cnt = 0
    pos_sales = Decimal(0)
    pos_paid = Decimal(0)
    if include_pos:
        pos_where = " AND ".join(pos_filters)
        pos_row = db.execute(
            text(
                f"""
                SELECT
                    COUNT(*) AS cnt,
                    COALESCE(SUM(total_amount), 0) AS total_sales,
                    COALESCE(SUM(paid_amount), 0) AS total_paid
                FROM pos_orders
                WHERE {pos_where}
                """
            ),
            params,
        ).fetchone()
        pos_cnt = int(pos_row.cnt or 0)
        pos_sales = Decimal(str(pos_row.total_sales or 0))
        pos_paid = Decimal(str(pos_row.total_paid or 0))

    total_sales = inv_sales + pos_sales
    total_paid = inv_paid + pos_paid
    total_due = total_sales - total_paid
    if total_due < 0:
        total_due = Decimal(0)

    return {
        "total_sales": total_sales,
        "invoice_count": inv_cnt + pos_cnt,
        "total_paid": total_paid,
        "total_due": total_due,
    }


def get_gl_profit_breakdown(
    db,
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    branch_ids: Optional[Sequence[int]] = None,
) -> Dict[str, Decimal]:
    """Return revenue / COGS / opex / gross & net profit from posted GL.

    Used by Dashboard (to expose explicit COGS and net_profit) and by
    Reports `/sales/summary` (profit block). Posted entries only.
    """
    params: Dict[str, Any] = {}
    where = ["je.status = 'posted'"]
    if start_date is not None:
        params["start_date"] = start_date
        where.append("je.entry_date >= :start_date")
    if end_date is not None:
        params["end_date"] = end_date
        where.append("je.entry_date <= :end_date")
    if branch_id is not None:
        params["branch_id"] = branch_id
        where.append("je.branch_id = :branch_id")
    elif branch_ids is not None:
        branch_ids = list(branch_ids)
        if branch_ids:
            params["branch_ids"] = branch_ids
            where.append("je.branch_id = ANY(:branch_ids)")
        else:
            where.append("1=0")

    row = db.execute(
        text(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN a.account_type = 'revenue'
                    THEN jl.credit - jl.debit ELSE 0 END), 0) AS revenue,
                COALESCE(SUM(CASE WHEN a.account_code LIKE 'CGS%'
                    THEN jl.debit - jl.credit ELSE 0 END), 0) AS cogs,
                COALESCE(SUM(CASE WHEN a.account_type = 'expense'
                                  AND a.account_code NOT LIKE 'CGS%'
                    THEN jl.debit - jl.credit ELSE 0 END), 0) AS opex
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            JOIN accounts a ON a.id = jl.account_id
            WHERE {" AND ".join(where)}
            """
        ),
        params,
    ).fetchone()

    revenue = Decimal(str(row.revenue or 0))
    cogs = Decimal(str(row.cogs or 0))
    opex = Decimal(str(row.opex or 0))
    return {
        "net_revenue": revenue,
        "cogs": cogs,
        "operating_expenses": opex,
        "gross_profit": revenue - cogs,
        "net_profit": revenue - cogs - opex,
    }

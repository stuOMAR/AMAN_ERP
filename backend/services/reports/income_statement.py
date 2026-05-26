"""T110: Income statement service — with optional header rows.

Reads ``reports.income_statement.include_headers`` setting to control
whether header rows (is_header=true) are included.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)
_D2 = Decimal("0.01")


def _money(value: Decimal) -> str:
    return str(value.quantize(_D2))


def get_income_statement(db: Any, tenant_id: str, company_id: str,
                         period_id: str | None = None,
                         start_date: str | None = None,
                         end_date: str | None = None,
                         include_headers: bool = True) -> dict[str, Any]:
    """Generate income statement from GL.

    Uses account_classifications for sign logic. Optionally includes
    header rows for grouped categories.

    Args:
        db: Database connection.
        tenant_id: Tenant identifier.
        company_id: Company identifier.
        period_id: Fiscal period ID (optional, used for MV lookup).
        start_date: Start date filter.
        end_date: End date filter.
        include_headers: Whether to include category header rows.

    Returns:
        Income statement dict with rows and totals.
    """
    from sqlalchemy import text
    from services.reports.rollup import to_decimal

    date_filter = ""
    params: dict[str, Any] = {"tid": tenant_id, "cid": company_id}

    account_code_sql = "COALESCE(NULLIF(a.account_code::text, ''), NULLIF(a.account_number::text, ''), a.id::text)"

    if period_id:
        date_filter = """
            AND EXISTS (
                SELECT 1
                FROM fiscal_periods p
                WHERE p.id::text = :period_id
                  AND je.entry_date::date BETWEEN p.start_date AND p.end_date
            )
        """
        params["period_id"] = period_id
    elif start_date and end_date:
        date_filter = "AND je.entry_date::date BETWEEN :start_date AND :end_date"
        params["start_date"] = start_date
        params["end_date"] = end_date

    try:
        result = db.execute(
            text(f"""
                SELECT
                                        ac.statement_category,
                    a.id AS account_id,
                    a.name AS account_name,
                                        {account_code_sql} AS account_code,
                                        CASE WHEN ac.sign = -1 THEN 'credit' ELSE 'debit' END AS normal_side,
                    COALESCE(SUM(jl.debit), 0) AS total_debit,
                    COALESCE(SUM(jl.credit), 0) AS total_credit
                FROM journal_lines jl
                JOIN journal_entries je ON je.id = jl.journal_entry_id
                JOIN accounts a ON a.id = jl.account_id
                                LEFT JOIN account_classifications ac
                                    ON ac.account_id = a.id
                                 AND ac.tenant_id = :tid
                                 AND ac.is_active = true
                                 AND ac.valid_from <= CURRENT_DATE
                                 AND (ac.valid_to IS NULL OR ac.valid_to >= CURRENT_DATE)
                                WHERE ac.statement_category IN ('revenue', 'expense', 'contra_revenue', 'contra_expense')
                  {date_filter}
                                GROUP BY ac.statement_category, a.id, a.name, {account_code_sql}, ac.sign
                                ORDER BY ac.statement_category, {account_code_sql}
            """),
            params,
        )
        rows = result.fetchall()
    except Exception as exc:
        logger.error("Income statement query failed: %s", exc)
        return {"rows": [], "totals": {"revenue": "0.00", "expense": "0.00", "net_income": "0.00"}}

    # Group by category
    categories: dict[str, list[dict]] = {}
    for row in rows:
        category = row[0] or "unknown"
        row[4] or "debit"
        debit = to_decimal(row[5])
        credit = to_decimal(row[6])

        if category in ("revenue", "contra_revenue"):
            amount = credit - debit
        else:
            amount = debit - credit

        entry = {
            "account_id": row[1],
            "account_name": row[2],
            "account_code": row[3],
            "amount": _money(amount),
            "is_header": False,
        }

        if category not in categories:
            categories[category] = []
        categories[category].append(entry)

    # Build output with optional headers
    output_rows = []
    total_revenue = Decimal("0")
    total_expense = Decimal("0")

    for cat_name in ["revenue", "contra_revenue", "expense", "contra_expense"]:
        if cat_name not in categories:
            continue

        entries = categories[cat_name]
        cat_total = sum(to_decimal(e["amount"]) for e in entries)

        if include_headers:
            output_rows.append({
                "category": cat_name,
                "account_name": cat_name.upper(),
                "amount": _money(cat_total),
                "is_header": True,
            })

        output_rows.extend(entries)

        if cat_name in ("revenue", "contra_revenue"):
            total_revenue += cat_total
        else:
            total_expense += cat_total

    net_income = total_revenue - total_expense

    return {
        "rows": output_rows,
        "totals": {
            "revenue": _money(total_revenue),
            "expense": _money(total_expense),
            "net_income": _money(net_income),
        },
    }

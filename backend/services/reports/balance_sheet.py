"""T109: Balance sheet service — classifier-driven sign logic.

Consumes ``account_classifications`` (feature 022) for sign rules.
No account-code range branching.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


def get_balance_sheet(db: Any, tenant_id: str, company_id: str,
                      as_of_date: str | None = None) -> dict[str, Any]:
    """Generate balance sheet from GL using account_classifications for sign rules.

    Args:
        db: Database connection.
        tenant_id: Tenant identifier.
        company_id: Company identifier.
        as_of_date: As-of date for the balance sheet.

    Returns:
        Balance sheet dict with assets, liabilities, equity sections.
    """
    from sqlalchemy import text
    from services.reports.rollup import to_decimal

    account_code_sql = "COALESCE(NULLIF(a.account_code::text, ''), NULLIF(a.account_number::text, ''), a.id::text)"
    date_filter = "AND je.entry_date::date <= :as_of_date" if as_of_date else ""
    params = {"tid": tenant_id, "cid": company_id}
    if as_of_date:
        params["as_of_date"] = as_of_date

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
                                WHERE 1 = 1
                  {date_filter}
                                GROUP BY ac.statement_category, a.id, a.name, {account_code_sql}, ac.sign
                                ORDER BY ac.statement_category, {account_code_sql}
            """),
            params,
        )
        rows = result.fetchall()
    except Exception as exc:
        logger.error("Balance sheet query failed: %s", exc)
        return {"assets": [], "liabilities": [], "equity": [], "total_assets": 0, "total_liabilities_equity": 0}

    assets = []
    liabilities = []
    equity = []

    for row in rows:
        category = row[0] or "unknown"
        normal_side = row[4] or "debit"
        debit = to_decimal(row[5])
        credit = to_decimal(row[6])

        # Apply sign based on normal_side from account_classifications
        if normal_side == "debit":
            balance = debit - credit
        else:
            balance = credit - debit

        entry = {
            "account_id": row[1],
            "account_name": row[2],
            "account_code": row[3],
            "balance": float(balance),
        }

        if category in ("asset", "contra_asset"):
            assets.append(entry)
        elif category in ("liability", "contra_liability"):
            liabilities.append(entry)
        elif category in ("equity", "contra_equity"):
            equity.append(entry)

    total_assets = sum(a["balance"] for a in assets)
    total_liabilities = sum(l["balance"] for l in liabilities)
    total_equity = sum(e["balance"] for e in equity)

    return {
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity,
        "total_liabilities_equity": total_liabilities + total_equity,
    }

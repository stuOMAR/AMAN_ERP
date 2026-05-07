"""T111/T112: Trial balance service — tolerance + opening-balance fix.

Reads ``reports.trial_balance.tolerance`` setting. Reports ``total_drift``
in the payload. Fixes opening-balance distribution for reverse-sign accounts.
"""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE = Decimal("0.01")


def get_trial_balance(db: Any, tenant_id: str, company_id: str,
                      as_of_date: str | None = None,
                      tolerance: float | None = None) -> dict[str, Any]:
    """Generate trial balance from GL.

    Uses account_classifications for sign logic. Reports drift from
    perfect balance.

    Args:
        db: Database connection.
        tenant_id: Tenant identifier.
        company_id: Company identifier.
        as_of_date: As-of date for the trial balance.
        tolerance: Configurable tolerance for balance drift.

    Returns:
        Trial balance dict with rows, balanced flag, and total_drift.
    """
    from sqlalchemy import text
    from services.reports.rollup import to_decimal

    tol = Decimal(str(tolerance)) if tolerance else DEFAULT_TOLERANCE
    account_code_sql = "COALESCE(NULLIF(a.account_code::text, ''), NULLIF(a.account_number::text, ''), a.id::text)"
    date_filter = "AND je.entry_date::date <= :as_of_date" if as_of_date else ""
    params: dict[str, Any] = {"tid": tenant_id, "cid": company_id}
    if as_of_date:
        params["as_of_date"] = as_of_date

    try:
        result = db.execute(
            text(f"""
                SELECT
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
                                GROUP BY a.id, a.name, {account_code_sql}, ac.sign
                                ORDER BY {account_code_sql}
            """),
            params,
        )
        rows = result.fetchall()
    except Exception as exc:
        logger.error("Trial balance query failed: %s", exc)
        return {"rows": [], "balanced": False, "total_drift": 0, "tolerance": float(tol)}

    output_rows = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")

    for row in rows:
        normal_side = row[3] or "debit"
        debit = to_decimal(row[4])
        credit = to_decimal(row[5])

        # For opening balances with reverse-sign behaviour
        # (e.g., contra accounts), use the normal_side to determine
        # the correct balance presentation
        if normal_side == "credit":
            # Credit-normal accounts: balance = credit - debit
            balance = credit - debit
        else:
            # Debit-normal accounts: balance = debit - credit
            balance = debit - credit

        output_rows.append({
            "account_id": row[0],
            "account_name": row[1],
            "account_code": row[2],
            "normal_side": normal_side,
            "debit": float(debit),
            "credit": float(credit),
            "balance": float(balance),
        })

        total_debit += debit
        total_credit += credit

    drift = (total_debit - total_credit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    balanced = abs(drift) <= tol

    return {
        "rows": output_rows,
        "balanced": balanced,
        "total_drift": float(drift),
        "tolerance": float(tol),
        "total_debit": float(total_debit.quantize(Decimal("0.01"))),
        "total_credit": float(total_credit.quantize(Decimal("0.01"))),
    }

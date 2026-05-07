"""T109: Sign rules — classifier-driven sign helper.

Centralises sign logic for financial reports. Account signs are derived
from ``account_classifications`` (feature 022), never from code prefixes.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_normal_side(db: Any, account_id: str) -> str:
    """Return the normal side ('debit' | 'credit') for an account.

    Falls back to 'debit' if classification not found.
    """
    from sqlalchemy import text

    try:
        result = db.execute(
            text("""
                SELECT CASE WHEN sign = -1 THEN 'credit' ELSE 'debit' END AS normal_side
                FROM account_classifications
                WHERE account_id = :aid
                  AND is_active = true
                  AND valid_from <= CURRENT_DATE
                  AND (valid_to IS NULL OR valid_to >= CURRENT_DATE)
                ORDER BY valid_from DESC
                LIMIT 1
            """),
            {"aid": account_id},
        )
        row = result.fetchone()
        return row[0] if row else "debit"
    except Exception:
        return "debit"


def get_category(db: Any, account_id: str) -> str:
    """Return the category (revenue, expense, asset, liability, equity) for an account."""
    from sqlalchemy import text

    try:
        result = db.execute(
            text("""
                SELECT statement_category
                FROM account_classifications
                WHERE account_id = :aid
                  AND is_active = true
                  AND valid_from <= CURRENT_DATE
                  AND (valid_to IS NULL OR valid_to >= CURRENT_DATE)
                ORDER BY valid_from DESC
                LIMIT 1
            """),
            {"aid": account_id},
        )
        row = result.fetchone()
        return row[0] if row else "unknown"
    except Exception:
        return "unknown"


def apply_sign(amount: float, normal_side: str, report_type: str = "balance") -> float:
    """Apply sign convention based on normal side and report type.

    Args:
        amount: The raw debit-credit amount.
        normal_side: The account's normal side ('debit' | 'credit').
        report_type: 'balance' for balance sheet, 'income' for income statement.

    Returns:
        The signed amount.
    """
    if report_type == "income":
        # Income statement: revenue is positive, expenses are positive
        return abs(amount)
    # Balance sheet: assets are positive, liabilities/equity negate
    if normal_side == "debit":
        return amount
    return -amount

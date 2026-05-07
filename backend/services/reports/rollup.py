"""T113: Rollup helpers — Decimal-only monetary aggregation.

Ensures all monetary values are Decimal, no float coercion.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


def to_decimal(value: Any) -> Decimal:
    """Convert a value to Decimal safely."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def sum_debits_credits(rows: list[dict[str, Any]]) -> dict[str, Decimal]:
    """Sum debit and credit columns from a list of rows.

    Returns dict with 'total_debit' and 'total_credit' as Decimal.
    """
    total_debit = Decimal("0")
    total_credit = Decimal("0")

    for row in rows:
        debit = to_decimal(row.get("debit", 0))
        credit = to_decimal(row.get("credit", 0))
        total_debit += debit
        total_credit += credit

    return {
        "total_debit": total_debit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        "total_credit": total_credit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        "net": (total_debit - total_credit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    }


def rollup_by_category(rows: list[dict[str, Any]], category_field: str = "category") -> dict[str, Decimal]:
    """Rollup amounts by category.

    Returns dict of {category: net_amount} as Decimal.
    """
    result: dict[str, Decimal] = {}

    for row in rows:
        category = row.get(category_field, "unknown")
        debit = to_decimal(row.get("debit", 0))
        credit = to_decimal(row.get("credit", 0))
        net = debit - credit

        if category not in result:
            result[category] = Decimal("0")
        result[category] += net

    # Quantize all values
    return {k: v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for k, v in result.items()}

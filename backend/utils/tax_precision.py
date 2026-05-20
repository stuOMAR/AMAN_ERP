"""Shared tax precision helpers.

Tax-facing code should keep calculations in Decimal and serialize money/rates
as strings so clients do not accidentally reintroduce binary float rounding.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

from fastapi import HTTPException, Request

from utils.currency_display import base_to_display_decimal


MONEY_PLACES = Decimal("0.01")
RATE_PLACES = Decimal("0.0001")
QTY_PLACES = Decimal("0.001")
CALCULATION_VERSION = "tax-v1.1.0"


def dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def q_money(value: Any) -> Decimal:
    return dec(value).quantize(MONEY_PLACES, ROUND_HALF_UP)


def q_rate(value: Any) -> Decimal:
    return dec(value).quantize(RATE_PLACES, ROUND_HALF_UP)


def q_qty(value: Any) -> Decimal:
    """Quantize a quantity to 3 decimals (UBL invoice line precision)."""
    return dec(value).quantize(QTY_PLACES, ROUND_HALF_UP)


def money_str(value: Any) -> str:
    return str(q_money(value))


def rate_str(value: Any) -> str:
    return str(q_rate(value))


def qty_str(value: Any) -> str:
    """3-dp quantity rendering for UBL InvoicedQuantity."""
    return str(q_qty(value))


def display_money_str(value: Any, display_meta: Mapping[str, Any]) -> str:
    return money_str(base_to_display_decimal(value, display_meta))


def get_idempotency_key(request: Request | None, *, fallback: str | None = None) -> str | None:
    if request is None:
        return fallback
    header = request.headers.get("Idempotency-Key") or request.headers.get("X-Idempotency-Key")
    key = (header or "").strip()
    return key or fallback


def require_idempotency_key(request: Request | None, *, operation: str = "tax mutation") -> str:
    key = get_idempotency_key(request)
    if not key:
        raise HTTPException(
            status_code=400,
            detail=f"Idempotency-Key header is required for {operation}",
        )
    return key


def serialize_tax_row(row, money_fields=None, rate_fields=None):
    """Convert a SQL row dict to JSON-safe with Decimal→string."""
    if hasattr(row, "_mapping"):
        d = dict(row._mapping)
    elif isinstance(row, dict):
        d = dict(row)
    else:
        d = dict(row)
    for f in (money_fields or []):
        if f in d and d[f] is not None:
            d[f] = money_str(d[f])
    for f in (rate_fields or []):
        if f in d and d[f] is not None:
            d[f] = rate_str(d[f])
    return d

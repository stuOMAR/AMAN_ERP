"""Centralized Decimal precision helpers for financial and inventory arithmetic.

Policy: All quantity, cost, and monetary calculations use Decimal(18,4).
Float is NOT used for any financial or inventory calculations.

Import this module instead of defining local _dec() helpers.
"""
from decimal import Decimal, ROUND_HALF_UP

# Precision constants
D2 = Decimal("0.01")
D4 = Decimal("0.0001")
D6 = Decimal("0.000001")


def dec(v) -> Decimal:
    """Convert any numeric value to Decimal safely."""
    return Decimal(str(v)) if v is not None else Decimal("0")


def round_amount(value, precision: int = 4) -> Decimal:
    """Round a monetary amount to the given decimal precision using ROUND_HALF_UP."""
    d = Decimal(str(value))
    quantizer = Decimal(10) ** -precision
    return d.quantize(quantizer, rounding=ROUND_HALF_UP)


def round_money(value) -> Decimal:
    """Round to 4 decimal places (NUMERIC(18,4))."""
    return round_amount(value, precision=4)


def round_fx_rate(value) -> Decimal:
    """Round an FX rate to 6 decimal places (NUMERIC(18,6))."""
    return round_amount(value, precision=6)

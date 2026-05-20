"""By-product allocation service.

Feature 023 — T082.  Contract: contracts/byproduct-allocation.md
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

logger = logging.getLogger(__name__)
_D4 = Decimal("0.0001")


def allocate(
    *,
    total_cost: Decimal,
    byproducts: list[dict],
    method: str = "by_quantity",
) -> list[dict]:
    """Allocate cost to by-products.

    Methods:
    - by_sales_value: proportional to sales_value
    - by_quantity: proportional to quantity
    - fixed: use fixed_cost per by-product

    Returns list of byproducts with allocated_cost added.
    """
    if not byproducts:
        return []

    if method == "by_sales_value":
        total_value = sum(Decimal(str(bp.get("sales_value", 0))) for bp in byproducts)
        if total_value > 0:
            for bp in byproducts:
                share = Decimal(str(bp.get("sales_value", 0))) / total_value
                bp["allocated_cost"] = (total_cost * share).quantize(_D4, rounding=ROUND_HALF_UP)
            return byproducts
        # Fallback to quantity
        logger.warning("byproduct.fallback_to_qty: sales_value inputs missing")
        method = "by_quantity"

    if method == "by_quantity":
        total_qty = sum(Decimal(str(bp.get("qty", 0))) for bp in byproducts)
        if total_qty > 0:
            for bp in byproducts:
                share = Decimal(str(bp.get("qty", 0))) / total_qty
                bp["allocated_cost"] = (total_cost * share).quantize(_D4, rounding=ROUND_HALF_UP)
            return byproducts

    if method == "fixed":
        for bp in byproducts:
            bp["allocated_cost"] = Decimal(str(bp.get("fixed_cost", 0)))
        return byproducts

    return byproducts

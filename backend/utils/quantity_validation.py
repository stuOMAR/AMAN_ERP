"""
Quantity validation utilities for unit-of-measure enforcement.

Discrete units (piece, box, carton) require integer quantities.
Continuous units (kg, meter, liter) allow decimal quantities.
"""

from sqlalchemy import text
from fastapi import HTTPException

from utils.i18n import http_error

# Units that require integer (whole number) quantities
DISCRETE_UNITS = {"قطعة", "علبة", "كرتون", "piece", "box", "carton", "unit"}


def is_discrete_unit(unit_name: str) -> bool:
    """Check if a unit name represents a discrete (countable) unit."""
    if not unit_name:
        return True  # Default to discrete for safety
    return unit_name.strip().lower() in {u.lower() for u in DISCRETE_UNITS}


def validate_quantity_for_product(db, product_id: int, quantity: float, request=None) -> None:
    """
    Validate that quantity is an integer if the product's unit is discrete.
    Raises HTTPException(400) if validation fails.
    """
    row = db.execute(text("""
        SELECT u.unit_name
        FROM products p
        LEFT JOIN product_units u ON p.unit_id = u.id
        WHERE p.id = :pid
    """), {"pid": product_id}).fetchone()

    if not row or not row.unit_name:
        return  # No unit info — skip validation

    if is_discrete_unit(row.unit_name):
        if quantity != int(quantity):
            raise HTTPException(**http_error(400, "qty_must_be_integer_for_unit", request, unit=row.unit_name, quantity=quantity))


def validate_quantities_for_products(db, items, request=None) -> None:
    """
    Batch version of quantity validation.
    `items` is an iterable of objects/dicts with product_id and quantity.
    """
    normalized = []
    for item in items:
        if isinstance(item, dict):
            pid = item.get("product_id")
            qty = item.get("quantity")
        else:
            pid = getattr(item, "product_id", None)
            qty = getattr(item, "quantity", None)
        if pid is not None and qty is not None:
            normalized.append((int(pid), qty))

    if not normalized:
        return

    product_ids = sorted({pid for pid, _ in normalized})
    rows = db.execute(text("""
        SELECT p.id AS product_id, u.unit_name
        FROM products p
        LEFT JOIN product_units u ON p.unit_id = u.id
        WHERE p.id = ANY(:pids)
    """), {"pids": product_ids}).fetchall()

    units_by_product = {row.product_id: row.unit_name for row in rows}
    for product_id, quantity in normalized:
        unit_name = units_by_product.get(product_id)
        if not unit_name:
            continue
        if is_discrete_unit(unit_name) and quantity != int(quantity):
            raise HTTPException(**http_error(400, "qty_must_be_integer_for_unit", request, unit=unit_name, quantity=quantity))

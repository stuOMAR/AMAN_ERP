"""WAC per warehouse — the canonical costing service.

Feature 023 — T069.  Contract: contracts/wac-per-warehouse.md
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)
_D4 = Decimal("0.0001")


class NegativeBalanceForbidden(Exception):
    def __init__(self, item_id: int, warehouse_id: int):
        self.item_id = item_id
        self.warehouse_id = warehouse_id
        super().__init__(f"Negative balance forbidden for item={item_id}, warehouse={warehouse_id}")


def apply_inbound(
    db: Any,
    *,
    item_id: int,
    warehouse_id: int,
    qty: Decimal,
    unit_cost: Decimal,
    source: str,
    tenant_id: int | None = None,
) -> Decimal:
    """Record inbound movement and update WAC at the warehouse level.

    New WAC = (existing_qty * existing_wac + qty * unit_cost) / (existing_qty + qty)

    Returns the new WAC.
    """
    if qty <= 0:
        return unit_cost

    # Get current stock
    current = _get_current_stock(db, item_id, warehouse_id, tenant_id)
    existing_qty = current["qty"]
    existing_wac = current["wac"]

    # Calculate new WAC
    if existing_qty + qty > 0:
        new_wac = ((existing_qty * existing_wac) + (qty * unit_cost)) / (existing_qty + qty)
    else:
        new_wac = unit_cost

    new_wac = new_wac.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    # Record transaction
    _insert_transaction(db, item_id, warehouse_id, qty, new_wac, "inbound", source, tenant_id)

    return new_wac


def apply_outbound(
    db: Any,
    *,
    item_id: int,
    warehouse_id: int,
    qty: Decimal,
    source: str,
    tenant_id: int | None = None,
    allow_negative: bool = False,
) -> Decimal:
    """Record outbound movement at current WAC. Returns cost used."""
    if qty <= 0:
        return Decimal(0)

    current = _get_current_stock(db, item_id, warehouse_id, tenant_id)
    available = current["qty"]

    if not allow_negative and available < qty:
        raise NegativeBalanceForbidden(item_id, warehouse_id)

    wac = current["wac"]
    cost = (qty * wac).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    _insert_transaction(db, item_id, warehouse_id, -qty, wac, "outbound", source, tenant_id)

    return cost


def apply_transfer(
    db: Any,
    *,
    item_id: int,
    src_warehouse_id: int,
    dst_warehouse_id: int,
    qty: Decimal,
    source: str,
    tenant_id: int | None = None,
) -> Decimal:
    """Transfer: outbound at src WAC, inbound at dst with same cost."""
    cost = apply_outbound(db, item_id=item_id, warehouse_id=src_warehouse_id, qty=qty, source=source, tenant_id=tenant_id)
    wac = cost / qty if qty > 0 else Decimal(0)
    apply_inbound(db, item_id=item_id, warehouse_id=dst_warehouse_id, qty=qty, unit_cost=wac, source=source, tenant_id=tenant_id)
    return cost


def read_wac(db: Any, *, item_id: int, warehouse_id: int, tenant_id: int | None = None) -> Decimal:
    """Read current WAC for an item at a warehouse."""
    return _get_current_stock(db, item_id, warehouse_id, tenant_id)["wac"]


def _get_current_stock(db: Any, item_id: int, warehouse_id: int, tenant_id: int | None) -> dict:
    """Get current stock qty and WAC for an item at a warehouse.

    INV-07 fix: reads from the ``inventory`` table (maintained running balance)
    instead of re-summing all historical inbound transactions, which was both
    incorrect (ignored outbound) and O(n) in transaction count.
    """
    row = db.execute(text("""
        SELECT COALESCE(quantity, 0)      AS qty,
               COALESCE(average_cost, 0) AS wac
        FROM inventory
        WHERE product_id = :item AND warehouse_id = :wid
    """), {"item": item_id, "wid": warehouse_id}).fetchone()

    if row:
        qty = Decimal(str(row.qty or 0))
        wac = Decimal(str(row.wac or 0))
    else:
        qty = Decimal(0)
        wac = Decimal(0)

    return {"qty": qty, "wac": wac}


def _insert_transaction(
    db: Any, item_id: int, warehouse_id: int,
    qty: Decimal, unit_cost: Decimal,
    direction: str, source: str, tenant_id: int | None,
) -> None:
    """Insert an inventory transaction.

    INV-01 fix: use str(Decimal) for SQL params — never float — to preserve
    NUMERIC(18,4) precision as required by Constitution §1 [CRITICAL].
    """
    db.execute(text("""
        INSERT INTO inventory_transactions (
            product_id, warehouse_id, quantity, unit_cost,
            transaction_type, created_at
        ) VALUES (
            :item, :wid, :qty, :cost,
            :type, clock_timestamp()
        )
    """), {
        "item": item_id, "wid": warehouse_id,
        "qty": str(qty), "cost": str(unit_cost),
        "type": "purchase" if direction == "inbound" else "sale",
    })

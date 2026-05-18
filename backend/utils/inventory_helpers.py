"""Inventory helpers shared across routers and services.

Single helper that writes ``inventory_transactions`` rows with consistent
``balance_before`` / ``balance_after`` snapshots, so every stock movement
leaves a complete audit trail.

The caller is expected to hold the ``inventory`` row lock (FOR UPDATE) and
to have already mutated ``inventory.quantity``.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from sqlalchemy import text

_D2 = Decimal("0.01")
_D4 = Decimal("0.0001")


def _dec(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def record_inventory_transaction(
    db: Any,
    *,
    product_id: int,
    warehouse_id: int,
    transaction_type: str,
    quantity: Any,
    unit_cost: Any = 0,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    reference_document: Optional[str] = None,
    notes: Optional[str] = None,
    user_id: Optional[int] = None,
    balance_after: Optional[Any] = None,
    balance_before: Optional[Any] = None,
) -> None:
    """Insert one ``inventory_transactions`` row with full snapshot fields.

    Either both ``balance_after`` and ``balance_before`` may be passed
    explicitly, or just ``balance_after`` and the helper will compute
    ``balance_before = balance_after - quantity``.

    When neither is supplied, the helper reads the current
    ``inventory.quantity`` for ``(product_id, warehouse_id)`` and uses it
    as ``balance_after``. Use this only when the inventory update has
    already been committed within the same transaction.
    """
    qty = _dec(quantity)
    cost = _dec(unit_cost)
    total_cost = (abs(qty) * cost).quantize(_D2, ROUND_HALF_UP)

    if balance_after is None:
        row = db.execute(
            text(
                "SELECT quantity FROM inventory "
                "WHERE product_id = :p AND warehouse_id = :w"
            ),
            {"p": product_id, "w": warehouse_id},
        ).fetchone()
        balance_after = _dec(row.quantity) if row else _dec(0)
    else:
        balance_after = _dec(balance_after)

    if balance_before is None:
        balance_before = balance_after - qty
    else:
        balance_before = _dec(balance_before)

    db.execute(
        text(
            """
            INSERT INTO inventory_transactions (
                product_id, warehouse_id, transaction_type,
                reference_type, reference_id, reference_document,
                quantity, balance_before, balance_after,
                unit_cost, total_cost, notes, created_by, created_at
            ) VALUES (
                :pid, :wid, :ttype,
                :rtype, :rid, :rdoc,
                :qty, :bbef, :baft,
                :uc, :tc, :notes, :uid, NOW()
            )
            """
        ),
        {
            "pid": product_id,
            "wid": warehouse_id,
            "ttype": transaction_type,
            "rtype": reference_type,
            "rid": reference_id,
            "rdoc": reference_document,
            "qty": qty,
            "bbef": balance_before,
            "baft": balance_after,
            "uc": cost.quantize(_D4, ROUND_HALF_UP),
            "tc": total_cost,
            "notes": notes,
            "uid": user_id,
        },
    )

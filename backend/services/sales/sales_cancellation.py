"""Sales/POS cancellation with full-line inventory pre-flight.

Feature 023 — T038.  Contract: contracts/sales-cancellation.md
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def inventory_preflight(db: Any, lines: list[dict], tenant_id: int) -> list[dict]:
    """Check stock availability for ALL lines. Returns list of shortages (empty = OK)."""
    shortages = []
    for line in lines:
        item_id = line.get("item_id") or line.get("product_id")
        warehouse_id = line.get("warehouse_id", 0)
        qty = Decimal(str(line.get("qty") or line.get("quantity", 0)))

        if qty <= 0:
            continue

        row = db.execute(
            text("""
                SELECT COALESCE(SUM(
                    CASE WHEN transaction_type IN ('purchase', 'return', 'adjustment_in', 'transfer_in')
                    THEN quantity ELSE -quantity END
                ), 0) as available
                FROM inventory_transactions
                WHERE tenant_id = :tid AND product_id = :item_id AND warehouse_id = :wid
            """),
            {"tid": tenant_id, "item_id": item_id, "wid": warehouse_id},
        ).fetchone()

        available = Decimal(str(row.available or 0)) if row else Decimal(0)
        if available < qty:
            shortages.append({
                "item_id": item_id,
                "warehouse_id": warehouse_id,
                "required": float(qty),
                "available": float(available),
            })

    return shortages


def cancel_invoice(
    db: Any,
    *,
    invoice_id: int,
    tenant_id: int,
    actor: dict,
    reason: str,
    restock_warehouse_id: int | None = None,
) -> dict:
    """Cancel a posted invoice with full-line inventory pre-flight."""
    # Lock invoice
    inv = db.execute(
        text("SELECT * FROM invoices WHERE id = :id AND tenant_id = :tid FOR UPDATE"),
        {"id": invoice_id, "tid": tenant_id},
    ).fetchone()

    if not inv:
        raise HTTPException(**http_error(404, "invoice_not_found"))

    inv = dict(inv._mapping)
    if inv.get("state") not in ("posted", "submitted"):
        raise HTTPException(status_code=409, detail={
            "code": "sales.invoice.state_invalid_transition",
            "message": i18n_message("cannot_cancel_invoice_state"),
        })

    # Get invoice lines
    lines = db.execute(
        text("SELECT * FROM invoice_lines WHERE invoice_id = :id AND tenant_id = :tid"),
        {"id": invoice_id, "tid": tenant_id},
    ).fetchall()
    lines = [dict(l._mapping) for l in lines]

    # Full-line pre-flight
    if restock_warehouse_id:
        shortages = inventory_preflight(db, lines, tenant_id)
        if shortages:
            raise HTTPException(status_code=409, detail={
                "code": "inventory.preflight_failed",
                "message": i18n_message("inventory.preflight_failed"),
                "shortages": shortages,
            })

    # Transition state
    from services.sales.invoice_state import transition
    result = transition(db, inv, "cancelled", actor=actor, reason=reason)

    # Audit
    try:
        from services.audit_writer import log_activity
        log_activity(
            db,
            action="sales.invoice.cancelled",
            entity_type="invoice",
            entity_id=invoice_id,
            details={"reason": reason, "restock_warehouse_id": restock_warehouse_id},
        )
    except Exception:
        pass

    return result

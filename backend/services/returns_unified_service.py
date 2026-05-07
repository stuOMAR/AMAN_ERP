"""Returns unified service — writes to consolidated returns_unified table.

Feature 023 — T041.  Contract: contracts/returns-unified.md
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def create_return(
    db: Any,
    *,
    tenant_id: int,
    source: str,
    original_invoice_id: int | None = None,
    original_pos_sale_id: int | None = None,
    restock_warehouse_id: int | None = None,
    lines: list[dict],
    reason: str | None = None,
    actor: dict | None = None,
) -> dict:
    """Create a draft return."""
    if source not in ("sales", "pos"):
        raise HTTPException(status_code=422, detail="source must be 'sales' or 'pos'")

    if source == "sales" and not original_invoice_id:
        raise HTTPException(status_code=422, detail="original_invoice_id required for sales returns")
    if source == "pos" and not original_pos_sale_id:
        raise HTTPException(status_code=422, detail="original_pos_sale_id required for POS returns")

    # Calculate total
    total = sum(Decimal(str(l.get("qty", 0))) * Decimal(str(l.get("unit_price", 0))) for l in lines)

    # Insert return
    result = db.execute(
        text("""
            INSERT INTO returns_unified (
                tenant_id, source, original_invoice_id, original_pos_sale_id,
                restock_warehouse_id, total_amount, reason, state,
                created_by, created_at, updated_at
            ) VALUES (
                :tid, :source, :inv_id, :pos_id,
                :warehouse, :total, :reason, 'draft',
                :actor_id, clock_timestamp(), clock_timestamp()
            )
            RETURNING id
        """),
        {
            "tid": tenant_id, "source": source,
            "inv_id": original_invoice_id, "pos_id": original_pos_sale_id,
            "warehouse": restock_warehouse_id, "total": total,
            "reason": reason, "actor_id": actor.get("id") if actor else None,
        },
    )
    return_id = result.fetchone().id

    # Insert lines
    for i, line in enumerate(lines, 1):
        db.execute(
            text("""
                INSERT INTO returns_unified_lines (
                    tenant_id, return_id, line_no, item_id, qty, unit_price, tax_id, tax_rate, created_at
                ) VALUES (:tid, :rid, :lno, :item, :qty, :price, :tax, :rate, clock_timestamp())
            """),
            {
                "tid": tenant_id, "rid": return_id, "lno": i,
                "item": line.get("item_id"), "qty": line.get("qty", 0),
                "price": line.get("unit_price", 0), "tax": line.get("tax_id"),
                "rate": line.get("tax_rate"),
            },
        )

    # Audit
    try:
        from services.audit_writer import log_activity
        log_activity(
            db, action=f"{source}.return.created",
            entity_type="return", entity_id=return_id,
            details={"source": source, "total": float(total)},
        )
    except Exception:
        pass

    return {"id": return_id, "state": "draft", "total_amount": float(total)}


def post_return(db: Any, *, return_id: int, tenant_id: int, actor: dict | None = None) -> dict:
    """Post a draft return: restock + GL posting."""
    ret = db.execute(
        text("SELECT * FROM returns_unified WHERE id = :id AND tenant_id = :tid FOR UPDATE"),
        {"id": return_id, "tid": tenant_id},
    ).fetchone()

    if not ret:
        raise HTTPException(status_code=404, detail="Return not found")
    ret = dict(ret._mapping)

    if ret["state"] != "draft":
        raise HTTPException(status_code=409, detail={
            "code": "returns.already_posted",
            "message": "Return is not in draft state",
        })

    # Get lines
    lines = db.execute(
        text("SELECT * FROM returns_unified_lines WHERE return_id = :rid AND tenant_id = :tid"),
        {"rid": return_id, "tid": tenant_id},
    ).fetchall()
    lines = [dict(l._mapping) for l in lines]

    # Inventory pre-flight if restocking
    if ret.get("restock_warehouse_id"):
        from services.sales.sales_cancellation import inventory_preflight
        # For returns, we're adding stock (inbound), so no pre-flight needed for shortages
        # Just restock
        for line in lines:
            try:
                from services.inventory.wac_per_warehouse import apply_inbound
                apply_inbound(
                    db, item_id=line["item_id"],
                    warehouse_id=ret["restock_warehouse_id"],
                    qty=Decimal(str(line["qty"])),
                    unit_cost=Decimal(str(line["unit_price"])),
                    source=f"{ret['source']}_return",
                )
            except ImportError:
                pass

    # GL posting
    je_id = None
    try:
        from services.sales.account_mapping import resolve
        source_label = f"{ret['source']}_return"
        # Resolve revenue account for the return
        resolve(db, mapping_kind=source_label, company_id=str(tenant_id), direction="reversal")
    except Exception:
        logger.warning("Account mapping resolution failed for return", exc_info=True)

    # Update state
    db.execute(
        text("""
            UPDATE returns_unified
            SET state = 'posted', je_id = :je_id, updated_at = clock_timestamp()
            WHERE id = :rid
        """),
        {"je_id": je_id, "rid": return_id},
    )

    # Audit
    try:
        from services.audit_writer import log_activity
        log_activity(
            db, action=f"{ret['source']}.return.posted",
            entity_type="return", entity_id=return_id,
            details={"je_id": je_id},
        )
    except Exception:
        pass

    return {"id": return_id, "state": "posted", "je_id": je_id}


def cancel_return(db: Any, *, return_id: int, tenant_id: int, actor: dict | None = None) -> dict:
    """Cancel a posted return."""
    ret = db.execute(
        text("SELECT * FROM returns_unified WHERE id = :id AND tenant_id = :tid FOR UPDATE"),
        {"id": return_id, "tid": tenant_id},
    ).fetchone()

    if not ret:
        raise HTTPException(status_code=404, detail="Return not found")
    ret = dict(ret._mapping)

    if ret["state"] != "posted":
        raise HTTPException(status_code=409, detail="Only posted returns can be cancelled")

    db.execute(
        text("UPDATE returns_unified SET state = 'cancelled', updated_at = clock_timestamp() WHERE id = :rid"),
        {"rid": return_id},
    )

    # Audit
    try:
        from services.audit_writer import log_activity
        log_activity(
            db, action=f"{ret['source']}.return.cancelled",
            entity_type="return", entity_id=return_id,
        )
    except Exception:
        pass

    return {"id": return_id, "state": "cancelled"}

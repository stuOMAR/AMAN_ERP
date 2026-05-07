"""Order → Invoice service.

Feature 023 — T033.  Contract: contracts/order-to-invoice.md
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def convert_order_to_invoice(
    db: Any,
    *,
    order_id: int,
    company_id: str,
    actor: dict,
    idempotency_key: str,
    posting_date: str | None = None,
    memo: str | None = None,
) -> dict:
    """Convert a confirmed SalesOrder into a posted Invoice exactly once.

    Steps:
    1. SELECT FOR UPDATE on sales_orders
    2. Idempotency check on (idempotency_key, sales_order_id)
    3. Validate order state = 'confirmed' and not already converted
    4. Snapshot lines into invoice_lines
    5. Insert invoice in 'draft' state
    6. Call invoice_state.transition('posted')
    7. Set converted_to_invoice_id on order
    8. Audit write

    Returns:
        Invoice dict with id, state, lines, totals, gl_je_id, zatca_outbox_id.
    """
    # 1. Lock order
    order = db.execute(
        text("""
            SELECT * FROM sales_orders
            WHERE id = :order_id AND tenant_id = :tenant_id
            FOR UPDATE
        """),
        {"order_id": order_id, "tenant_id": actor.get("tenant_id")},
    ).fetchone()

    if not order:
        raise HTTPException(status_code=404, detail="Sales order not found")

    order = dict(order._mapping)

    # 2. Idempotency check
    existing = db.execute(
        text("""
            SELECT * FROM invoices
            WHERE tenant_id = :tenant_id
              AND sales_order_id = :order_id
              AND idempotency_key = :key
        """),
        {"tenant_id": actor.get("tenant_id"), "order_id": order_id, "key": idempotency_key},
    ).fetchone()

    if existing:
        return dict(existing._mapping)

    # 3. Validate
    if order.get("state") != "confirmed" and order.get("status") != "confirmed":
        raise HTTPException(status_code=409, detail={
            "code": "sales_order.invalid_state",
            "message": "Order must be in 'confirmed' state",
        })

    if order.get("converted_to_invoice_id"):
        raise HTTPException(status_code=409, detail={
            "code": "sales.order_already_converted",
            "message": "Order has already been converted to an invoice",
        })

    # 4. Snapshot lines
    lines = db.execute(
        text("""
            SELECT * FROM sales_order_lines
            WHERE order_id = :order_id AND tenant_id = :tenant_id
            ORDER BY line_no
        """),
        {"order_id": order_id, "tenant_id": actor.get("tenant_id")},
    ).fetchall()

    if not lines:
        raise HTTPException(status_code=422, detail="Order has no lines")

    # 5. Insert invoice in draft
    inv_result = db.execute(
        text("""
            INSERT INTO invoices (
                tenant_id, invoice_type, invoice_date, party_id,
                sales_order_id, idempotency_key, notes, status, state,
                created_by, created_at, updated_at
            ) VALUES (
                :tenant_id, 'sales', COALESCE(:posting_date, CURRENT_DATE),
                :party_id, :order_id, :idempotency_key, :memo, 'draft', 'draft',
                :actor_id, clock_timestamp(), clock_timestamp()
            )
            RETURNING id
        """),
        {
            "tenant_id": actor.get("tenant_id"),
            "posting_date": posting_date,
            "party_id": order.get("customer_id") or order.get("party_id"),
            "order_id": order_id,
            "idempotency_key": idempotency_key,
            "memo": memo,
            "actor_id": actor.get("id"),
        },
    )
    invoice_id = inv_result.fetchone().id

    # Insert invoice lines
    for line in lines:
        line = dict(line._mapping)
        db.execute(
            text("""
                INSERT INTO invoice_lines (
                    tenant_id, invoice_id, product_id, description,
                    quantity, unit_price, tax_rate, discount_amount, created_at
                ) VALUES (
                    :tenant_id, :invoice_id, :product_id, :description,
                    :qty, :unit_price, :tax_rate, :discount, clock_timestamp()
                )
            """),
            {
                "tenant_id": actor.get("tenant_id"),
                "invoice_id": invoice_id,
                "product_id": line.get("product_id"),
                "description": line.get("description", ""),
                "qty": line.get("quantity", 0),
                "unit_price": line.get("unit_price", 0),
                "tax_rate": line.get("tax_rate", 0),
                "discount": line.get("discount_amount", 0),
            },
        )

    # 6. Transition to posted
    from services.sales.invoice_state import transition
    inv_row = db.execute(
        text("SELECT * FROM invoices WHERE id = :id"),
        {"id": invoice_id},
    ).fetchone()
    invoice = dict(inv_row._mapping)
    invoice = transition(db, invoice, "posted", actor=actor)

    # 7. Link order to invoice
    db.execute(
        text("""
            UPDATE sales_orders
            SET converted_to_invoice_id = :inv_id, updated_at = clock_timestamp()
            WHERE id = :order_id
        """),
        {"inv_id": invoice_id, "order_id": order_id},
    )

    # 8. Audit
    try:
        from services.audit_writer import log_activity
        log_activity(
            db,
            action="sales.invoice.created_from_order",
            entity_type="invoice",
            entity_id=invoice_id,
            details={
                "order_id": order_id,
                "idempotency_key": idempotency_key,
            },
        )
    except Exception:
        logger.warning("Audit write failed for order→invoice", exc_info=True)

    return invoice

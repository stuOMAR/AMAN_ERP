"""POS cancellation endpoint.

Feature 023 — T039.  POST /pos/sales/{id}/cancel
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from database import get_company_db
from routers.auth import get_current_user
from schemas import UserResponse

router = APIRouter()


class PosCancellationRequest(BaseModel):
    reason: Optional[str] = None
    restock_warehouse_id: Optional[int] = None


def get_db(current_user: UserResponse = Depends(get_current_user)):
    yield from get_company_db(current_user.company_id)


@router.post("/pos/sales/{sale_id}/cancel")
async def cancel_pos_sale(
    sale_id: int,
    body: PosCancellationRequest,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import text

    # POS orders are in pos_orders table
    order = db.execute(
        text("""
            SELECT id, order_number, status, warehouse_id, session_id
            FROM pos_orders
            WHERE id = :order_id
        """),
        {"order_id": sale_id},
    ).fetchone()

    if not order:
        raise HTTPException(status_code=404, detail="POS order not found")

    if order.status == 'cancelled':
        raise HTTPException(status_code=400, detail="Order already cancelled")

    if order.status != 'paid':
        raise HTTPException(status_code=400, detail="Only paid orders can be cancelled")

    # Get order lines for restocking
    lines = db.execute(
        text("""
            SELECT product_id, quantity, warehouse_id
            FROM pos_order_lines
            WHERE order_id = :order_id
        """),
        {"order_id": sale_id},
    ).fetchall()

    restock_wh = body.restock_warehouse_id or order.warehouse_id

    # Restock inventory if warehouse specified
    if restock_wh:
        for line in lines:
            db.execute(text("""
                UPDATE inventory
                SET quantity = quantity + :qty
                WHERE product_id = :pid AND warehouse_id = :wh
            """), {"qty": line.quantity, "pid": line.product_id, "wh": restock_wh})

            # Log inventory transaction
            db.execute(text("""
                INSERT INTO inventory_transactions (
                    product_id, warehouse_id, transaction_type,
                    reference_type, reference_id, quantity, created_by
                ) VALUES (
                    :pid, :wh, 'return_in',
                    'pos_cancellation', :order_id,
                    :qty, :uid
                )
            """), {"pid": line.product_id, "wh": restock_wh, "order_id": sale_id, "qty": line.quantity, "uid": current_user.id})

    # Update order status
    db.execute(text("""
        UPDATE pos_orders SET status = 'cancelled', note = COALESCE(note || ' | ', '') || :reason
        WHERE id = :order_id
    """), {"order_id": sale_id, "reason": body.reason or "Cancelled"})

    db.commit()

    return {"id": sale_id, "status": "cancelled", "message": "POS order cancelled successfully"}

"""Production approval endpoint.

Feature 023 — T084.  POST /manufacturing/orders/{id}/approve
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/manufacturing/orders", tags=["manufacturing"])


@router.post("/{order_id}/approve")
async def approve_production_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    from utils.permissions import get_current_user
    from sqlalchemy import text

    user = get_current_user(request)
    tid = user.get("tenant_id", 0)

    result = db.execute(
        text("""
            UPDATE manufacturing_orders
            SET state = 'released',
                approved_by = :uid,
                approved_at = clock_timestamp(),
                updated_at = clock_timestamp()
            WHERE id = :id AND tenant_id = :tid AND state = 'pending_approval'
            RETURNING id, state
        """),
        {"id": order_id, "tid": tid, "uid": user.get("id")},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(**http_error(404, ("production_order_not_pending", request)))

    # Audit
    try:
        from services.audit_writer import log_activity
        log_activity(
            db,
            action="mfg.order.approved",
            entity_type="manufacturing_order",
            entity_id=order_id,
            details={"approved_by": user.get("id")},
        )
    except Exception:
        pass

    db.commit()
    return {"id": row.id, "state": row.state}

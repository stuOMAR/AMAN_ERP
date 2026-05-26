"""Production approval endpoint.

Feature 023 — T084.  POST /manufacturing/orders/{id}/approve
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_company_db
from routers.auth import get_current_user
from schemas import UserResponse
from utils.i18n import http_error
from utils.permissions import require_module, require_permission

router = APIRouter(
    prefix="/manufacturing/orders",
    tags=["manufacturing"],
    dependencies=[Depends(require_module("manufacturing"))],
)


def get_db(current_user: UserResponse = Depends(get_current_user)):
    yield from get_company_db(current_user.company_id)


def _actor(current_user: UserResponse) -> dict:
    return {
        "id": current_user.id,
        "user_id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
        "company_id": current_user.company_id,
        "tenant_id": current_user.company_id,
        "permissions": current_user.permissions or [],
    }


@router.post("/{order_id}/approve", dependencies=[Depends(require_permission("manufacturing.manage"))])
async def approve_production_order(
    order_id: int,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import text

    user = _actor(current_user)
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
        raise HTTPException(**http_error(404, "production_order_not_pending", request))

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

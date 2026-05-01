"""pos sub-router — split from monolithic pos.py (T6.3).

Mounted under the parent router via pos/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging
from database import get_company_db
from routers.auth import get_current_user
from utils.permissions import require_permission, validate_branch_access, require_module
from utils.fiscal_lock import check_fiscal_period_open
from utils.audit import log_activity
from schemas import UserResponse
from schemas.pos import SessionCreate, SessionClose, SessionResponse, POSProductResponse, OrderCreate, OrderResponse, ReturnCreate
from services.gl_service import create_journal_entry as gl_create_journal_entry

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

def get_db(current_user: UserResponse = Depends(get_current_user)):
    yield from get_company_db(current_user.company_id)

router = APIRouter()

from .core import _D2, _D4, get_db

@router.get("/kitchen/orders", dependencies=[Depends(require_permission("pos.view"))], response_model=List[Dict[str, Any]])
def kitchen_orders(
    station: Optional[str] = None,
    status: Optional[str] = "pending",
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    q = "SELECT * FROM pos_kitchen_orders WHERE 1=1"
    params = {}
    if station:
        q += " AND station = :station"
        params["station"] = station
    if status:
        q += " AND status = :status"
        params["status"] = status
    q += " ORDER BY priority DESC, sent_at ASC"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/kitchen/orders", dependencies=[Depends(require_permission("pos.create"))], response_model=Dict[str, Any])
def send_to_kitchen(data: dict, request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send order items to kitchen."""
    items = data.get("items", [])
    results = []
    for item in items:
        row = db.execute(text("""
            INSERT INTO pos_kitchen_orders (order_id, order_line_id, product_id, product_name,
                quantity, notes, station, priority, branch_id)
            VALUES (:oid, :olid, :pid, :pname, :qty, :notes, :station, :priority, :branch)
            RETURNING *
        """), {
            "oid": data.get("order_id"),
            "olid": item.get("order_line_id"),
            "pid": item.get("product_id"),
            "pname": item.get("product_name"),
            "qty": item.get("quantity", 1),
            "notes": item.get("notes"),
            "station": item.get("station", "main"),
            "priority": item.get("priority", 0),
            "branch": data.get("branch_id"),
        }).fetchone()
        results.append(dict(row._mapping))
    db.commit()
    log_activity(
        db=db,
        user_id=current_user.id,
        action="kitchen_order_created",
        resource_type="pos_kitchen_order",
        resource_id=data.get("order_id"),
        details={"items_count": len(items), "order_id": data.get("order_id")},
        request=request,
    )
    return results


@router.put("/kitchen/orders/{ko_id}/status", dependencies=[Depends(require_permission("pos.manage"))], response_model=Dict[str, Any])
def update_kitchen_status(ko_id: int, data: dict, request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    new_status = data.get("status")
    ts_field = {"accepted": "accepted_at", "ready": "ready_at", "served": "served_at"}.get(new_status)
    if ts_field:
        db.execute(text(f"UPDATE pos_kitchen_orders SET status = :s, {ts_field} = NOW() WHERE id = :id"), {"s": new_status, "id": ko_id})
    else:
        db.execute(text("UPDATE pos_kitchen_orders SET status = :s WHERE id = :id"), {"s": new_status, "id": ko_id})
    db.commit()
    log_activity(
        db=db,
        user_id=current_user.id,
        action="kitchen_status_changed",
        resource_type="pos_kitchen_order",
        resource_id=ko_id,
        details={"new_status": new_status},
        request=request,
    )
    return {"message": f"Kitchen order {ko_id} → {new_status}"}


# ===================== B7: PWA Support =====================


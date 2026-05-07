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
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access, require_module
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

@router.get("/promotions", dependencies=[Depends(require_permission("pos.view"))], response_model=List[Dict[str, Any]])
def list_promotions(
    active_only: bool = True,
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List Promotions."""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    q = "SELECT * FROM pos_promotions WHERE 1=1"
    params = {}
    q += f" {branch_scope_filter_from_scope(branch_scope, 'branch_id', params)}"
    if active_only:
        q += " AND is_active = true AND (end_date IS NULL OR end_date > NOW())"
    q += " ORDER BY created_at DESC"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/promotions", dependencies=[Depends(require_permission("pos.manage"))], response_model=Dict[str, Any])
def create_promotion(
    data: dict,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create Promotion."""
    branch_id = data.get("branch_id")
    if branch_id:
        validate_branch_access(current_user, branch_id)

    result = db.execute(text("""
        INSERT INTO pos_promotions (name, promotion_type, value, buy_qty, get_qty, coupon_code,
            applicable_products, applicable_categories, min_order_amount, start_date, end_date,
            is_active, branch_id, created_by)
        VALUES (:name, :type, :value, :buy, :get, :coupon,
            :products, :categories, :min_amt, :start, :end,
            :active, :branch, :uid)
        RETURNING *
    """), {
        "name": data.get("name"),
        "type": data.get("promotion_type", "percentage"),
        "value": data.get("value", 0),
        "buy": data.get("buy_qty"),
        "get": data.get("get_qty"),
        "coupon": data.get("coupon_code"),
        "products": data.get("applicable_products"),
        "categories": data.get("applicable_categories"),
        "min_amt": data.get("min_order_amount", 0),
        "start": data.get("start_date"),
        "end": data.get("end_date"),
        "active": data.get("is_active", True),
        "branch": branch_id,
        "uid": current_user.id,
    })
    db.commit()
    row = dict(result.fetchone()._mapping)

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="create_promotion", resource_type="pos_promotion",
        resource_id=str(row.get("id")),
        details={"name": data.get("name"), "type": data.get("promotion_type")},
        request=request, branch_id=branch_id
    )

    return row


@router.put("/promotions/{promo_id}", dependencies=[Depends(require_permission("pos.manage"))], response_model=Dict[str, Any])
def update_promotion(
    promo_id: int,
    data: dict,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update Promotion."""
    sets = []
    params = {"id": promo_id}
    for field in ["name", "promotion_type", "value", "buy_qty", "get_qty", "coupon_code",
                  "applicable_products", "applicable_categories", "min_order_amount",
                  "start_date", "end_date", "is_active"]:
        if field in data:
            sets.append(f"{field} = :{field}")
            params[field] = data[field]
    if not sets:
        raise HTTPException(status_code=400, detail="No fields to update")
    sets.append("updated_at = NOW()")
    sql = f"UPDATE pos_promotions SET {', '.join(sets)} WHERE id = :id RETURNING *"
    row = db.execute(text(sql), params).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Promotion not found")
    db.commit()

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="update_promotion", resource_type="pos_promotion",
        resource_id=str(promo_id),
        details={"updated_fields": list(data.keys())},
        request=request
    )

    return dict(row._mapping)


@router.delete("/promotions/{promo_id}", dependencies=[Depends(require_permission("pos.manage"))], response_model=Dict[str, Any])
def delete_promotion(promo_id: int, request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete Promotion."""
    db.execute(text("DELETE FROM pos_promotions WHERE id = :id"), {"id": promo_id})
    db.commit()

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="delete_promotion", resource_type="pos_promotion",
        resource_id=str(promo_id), request=request
    )

    return {"message": "Deleted"}


@router.post("/promotions/validate", dependencies=[Depends(require_permission("pos.view"))], response_model=Dict[str, Any])
def validate_coupon(
    data: dict,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Validate a coupon code and return applicable promotion."""
    code = data.get("coupon_code", "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Coupon code required")
    promo = db.execute(text("""
        SELECT * FROM pos_promotions
        WHERE coupon_code = :code AND is_active = true
          AND (start_date IS NULL OR start_date <= NOW())
          AND (end_date IS NULL OR end_date > NOW())
    """), {"code": code}).fetchone()
    if not promo:
        raise HTTPException(status_code=404, detail="Invalid or expired coupon")
    return dict(promo._mapping)


# ---------- POS-004: Loyalty Program ----------


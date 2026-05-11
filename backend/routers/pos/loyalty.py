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

from .core import _D2, _D4, _dec, get_db

@router.get("/loyalty/programs", dependencies=[Depends(require_permission("pos.view"))], response_model=List[Dict[str, Any]])
def list_loyalty_programs(
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List Loyalty Programs."""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    params = {}
    branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", params)
    rows = db.execute(text(f"SELECT * FROM pos_loyalty_programs WHERE is_active = true {branch_filter} ORDER BY id"), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/loyalty/programs", dependencies=[Depends(require_permission("pos.manage"))], response_model=Dict[str, Any])
def create_loyalty_program(data: dict, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create Loyalty Program."""
    import json
    branch_id = data.get("branch_id")
    if branch_id:
        validate_branch_access(current_user, branch_id)
    result = db.execute(text("""
        INSERT INTO pos_loyalty_programs (name, points_per_unit, currency_per_point, min_points_redeem, tier_rules, is_active, branch_id)
        VALUES (:name, :ppu, :cpp, :min, :tiers::jsonb, :active, :branch)
        RETURNING *
    """), {
        "name": data["name"],
        "ppu": data.get("points_per_unit", 1),
        "cpp": data.get("currency_per_point", 0.01),
        "min": data.get("min_points_redeem", 100),
        "tiers": json.dumps(data.get("tier_rules", [])),
        "active": data.get("is_active", True),
        "branch": branch_id,
    })
    db.commit()
    return dict(result.fetchone()._mapping)


@router.get("/loyalty/customer/{party_id}", dependencies=[Depends(require_permission("pos.view"))], response_model=Dict[str, Any])
def get_customer_loyalty(party_id: int, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get Customer Loyalty."""
    row = db.execute(text("""
        SELECT lp.*, prg.name as program_name, prg.currency_per_point
        FROM pos_loyalty_points lp
        JOIN pos_loyalty_programs prg ON lp.program_id = prg.id
        WHERE lp.party_id = :pid
    """), {"pid": party_id}).fetchone()
    if not row:
        return {"party_id": party_id, "balance": 0, "tier": "standard", "enrolled": False}
    return {**dict(row._mapping), "enrolled": True}


@router.post("/loyalty/enroll", dependencies=[Depends(require_permission("pos.manage"))], response_model=Dict[str, Any])
def enroll_customer(data: dict, request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    """Enroll Customer."""
    existing = db.execute(text(
        "SELECT id FROM pos_loyalty_points WHERE party_id = :pid AND program_id = :prog"
    ), {"pid": data["party_id"], "prog": data["program_id"]}).fetchone()
    if existing:
        raise HTTPException(**http_error(400, "customer_already_enrolled", request))
    result = db.execute(text("""
        INSERT INTO pos_loyalty_points (program_id, party_id, points_earned, points_redeemed, balance, tier)
        VALUES (:prog, :pid, 0, 0, 0, 'standard')
        RETURNING *
    """), {"prog": data["program_id"], "pid": data["party_id"]})
    db.commit()
    row = dict(result.fetchone()._mapping)

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="enroll_loyalty", resource_type="pos_loyalty",
        resource_id=str(row.get("id")),
        details={"party_id": data["party_id"], "program_id": data["program_id"]},
        request=request
    )

    return row


@router.post("/loyalty/earn", dependencies=[Depends(require_permission("pos.create"))], response_model=Dict[str, Any])
def earn_points(data: dict, request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    """Award loyalty points after a sale."""
    loyalty = db.execute(text("SELECT * FROM pos_loyalty_points WHERE party_id = :pid"), {"pid": data["party_id"]}).fetchone()
    if not loyalty:
        raise HTTPException(**http_error(404, "customer_not_enrolled_in_loyalty", request))
    program = db.execute(text("SELECT * FROM pos_loyalty_programs WHERE id = :id"), {"id": loyalty.program_id}).fetchone()
    points = (_dec(data.get("amount", 0)) * _dec(program.points_per_unit)).quantize(_D2, ROUND_HALF_UP)
    db.execute(text("""
        UPDATE pos_loyalty_points SET points_earned = points_earned + :pts, balance = balance + :pts,
            last_activity_at = NOW() WHERE id = :id
    """), {"pts": points, "id": loyalty.id})
    db.execute(text("""
        INSERT INTO pos_loyalty_transactions (loyalty_id, order_id, txn_type, points, description)
        VALUES (:lid, :oid, 'earn', :pts, :desc)
    """), {"lid": loyalty.id, "oid": data.get("order_id"), "pts": points, "desc": "Earned from order"})
    db.commit()

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="earn_loyalty_points", resource_type="pos_loyalty",
        resource_id=str(loyalty.id),
        details={"party_id": data["party_id"], "points": str(points), "order_id": data.get("order_id")},
        request=request
    )

    return {"points_earned": str(points), "new_balance": str((_dec(loyalty.balance) + points).quantize(_D2, ROUND_HALF_UP))}


@router.post("/loyalty/redeem", dependencies=[Depends(require_permission("pos.create"))], response_model=Dict[str, Any])
def redeem_points(data: dict, request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    """Redeem loyalty points as discount."""
    loyalty = db.execute(text("SELECT * FROM pos_loyalty_points WHERE party_id = :pid"), {"pid": data["party_id"]}).fetchone()
    if not loyalty:
        raise HTTPException(**http_error(404, "customer_not_enrolled", request))
    points = _dec(data.get("points", 0))
    if points > _dec(loyalty.balance):
        raise HTTPException(**http_error(400, "insufficient_points", request))
    program = db.execute(text("SELECT * FROM pos_loyalty_programs WHERE id = :id"), {"id": loyalty.program_id}).fetchone()
    if points < _dec(program.min_points_redeem):
        raise HTTPException(status_code=400, detail=i18n_message("min_points_to_redeem", request))
    discount_value = (points * _dec(program.currency_per_point)).quantize(_D2, ROUND_HALF_UP)
    db.execute(text("""
        UPDATE pos_loyalty_points SET points_redeemed = points_redeemed + :pts, balance = balance - :pts,
            last_activity_at = NOW() WHERE id = :id
    """), {"pts": points, "id": loyalty.id})
    db.execute(text("""
        INSERT INTO pos_loyalty_transactions (loyalty_id, order_id, txn_type, points, description)
        VALUES (:lid, :oid, 'redeem', :pts, :desc)
    """), {"lid": loyalty.id, "oid": data.get("order_id"), "pts": -points, "desc": "Redeemed for discount"})
    db.commit()

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="redeem_loyalty_points", resource_type="pos_loyalty",
        resource_id=str(loyalty.id),
        details={"party_id": data["party_id"], "points": str(points), "discount_value": str(discount_value)},
        request=request
    )

    return {"points_redeemed": str(points), "discount_value": str(discount_value), "new_balance": str((_dec(loyalty.balance) - points).quantize(_D2, ROUND_HALF_UP))}


# ---------- POS-006: Session Reports (Enhanced) ----------


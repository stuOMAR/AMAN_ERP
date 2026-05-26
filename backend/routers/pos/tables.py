"""pos sub-router — split from monolithic pos.py (T6.3).

Mounted under the parent router via pos/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from decimal import Decimal
import logging
from routers.auth import get_current_user
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access
from utils.audit import log_activity
from schemas import UserResponse

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter()

from .core import get_db  # noqa: E402

@router.get("/tables", dependencies=[Depends(require_permission("pos.view"))], response_model=List[Dict[str, Any]])
def list_tables(
    branch_id: Optional[int] = None,
    floor: Optional[str] = None,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List Tables."""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    q = "SELECT * FROM pos_tables WHERE is_active = true"
    params = {}
    q += f" {branch_scope_filter_from_scope(branch_scope, 'branch_id', params)}"
    if floor:
        q += " AND floor = :floor"
        params["floor"] = floor
    q += " ORDER BY floor, table_number"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/tables", dependencies=[Depends(require_permission("pos.manage"))], response_model=Dict[str, Any])
def create_table(data: dict, request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create Table."""
    branch_id = data.get("branch_id")
    if branch_id:
        validate_branch_access(current_user, branch_id)

    result = db.execute(text("""
        INSERT INTO pos_tables (table_number, table_name, floor, capacity, shape, pos_x, pos_y, branch_id)
        VALUES (:num, :name, :floor, :cap, :shape, :x, :y, :branch)
        RETURNING *
    """), {
        "num": data["table_number"],
        "name": data.get("table_name"),
        "floor": data.get("floor", "main"),
        "cap": data.get("capacity", 4),
        "shape": data.get("shape", "square"),
        "x": data.get("pos_x", 0),
        "y": data.get("pos_y", 0),
        "branch": branch_id,
    })
    db.commit()
    row = dict(result.fetchone()._mapping)

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="create_pos_table", resource_type="pos_table",
        resource_id=str(row.get("id")),
        details={"table_number": data["table_number"]},
        request=request, branch_id=branch_id
    )

    return row


@router.put("/tables/{table_id}", dependencies=[Depends(require_permission("pos.manage"))], response_model=Dict[str, Any])
def update_table(request: Request, table_id: int, data: dict, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    """Update Table."""
    sets, params = [], {"id": table_id}
    for f in ["table_number", "table_name", "floor", "capacity", "shape", "pos_x", "pos_y", "status", "is_active"]:
        if f in data:
            sets.append(f"{f} = :{f}")
            params[f] = data[f]
    if not sets:
        raise HTTPException(**http_error(400, "pos_no_fields", request))
    row = db.execute(text(f"UPDATE pos_tables SET {', '.join(sets)} WHERE id = :id RETURNING *"), params).fetchone()
    if not row:
        raise HTTPException(**http_error(404, "pos_table_not_found", request))
    db.commit()
    return dict(row._mapping)


@router.delete("/tables/{table_id}", dependencies=[Depends(require_permission("pos.manage"))], response_model=Dict[str, Any])
def delete_table(request: Request, table_id: int, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete Table."""
    db.execute(text("UPDATE pos_tables SET is_active = false WHERE id = :id"), {"id": table_id})
    db.commit()
    return {"message": i18n_message("pos_table_deactivated", request)}


@router.post("/tables/{table_id}/seat", dependencies=[Depends(require_permission("pos.create"))], response_model=Dict[str, Any])
def seat_table(table_id: int, data: dict, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    """Seat Table."""
    db.execute(text("UPDATE pos_tables SET status = 'occupied' WHERE id = :id"), {"id": table_id})
    result = db.execute(text("""
        INSERT INTO pos_table_orders (table_id, guests, waiter_id, status)
        VALUES (:tid, :guests, :waiter, 'seated')
        RETURNING *
    """), {"tid": table_id, "guests": data.get("guests", 1), "waiter": current_user.id})
    db.commit()
    return dict(result.fetchone()._mapping)


@router.post("/tables/{table_id}/clear", dependencies=[Depends(require_permission("pos.create"))], response_model=Dict[str, Any])
def clear_table(request: Request, table_id: int, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    """Clear Table."""
    db.execute(text("UPDATE pos_tables SET status = 'available' WHERE id = :id"), {"id": table_id})
    db.execute(text("""
        UPDATE pos_table_orders SET status = 'cleared', cleared_at = NOW()
        WHERE table_id = :tid AND status = 'seated'
    """), {"tid": table_id})
    db.commit()
    return {"message": i18n_message("pos_table_cleared", request)}


# ---------- POS-008: Kitchen Display System ----------


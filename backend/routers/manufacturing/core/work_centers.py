"""core sub-router — split from monolithic core.py (T6.3).

Mounted under the parent router via core/__init__.py.
"""
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from routers.auth import get_current_user
from utils.permissions import require_permission, resolve_branch_scope
from database import get_db_connection
from utils.audit import log_activity
from schemas import UserResponse
from schemas.manufacturing_advanced import (
    WorkCenterCreate, WorkCenterResponse
)

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/work-centers", response_model=List[WorkCenterResponse], dependencies=[Depends(require_permission("manufacturing.view"))])
def list_work_centers(
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """List Work Centers."""
    resolve_branch_scope(current_user, branch_id)
    conn = get_db_connection(current_user.company_id)
    try:
        query = "SELECT * FROM work_centers WHERE is_deleted = false"
        params = {}
        query += " ORDER BY name"
        rows = conn.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        conn.close()

@router.post("/work-centers", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.create"]))], response_model=Dict[str, Any])
def create_work_center(wc: WorkCenterCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Create Work Center."""
    conn = get_db_connection(current_user.company_id)
    try:
        new_wc = conn.execute(text("""
            INSERT INTO work_centers (name, code, capacity_per_day, cost_per_hour, location, status, cost_center_id, default_expense_account_id)
            VALUES (:name, :code, :cap, :cost, :loc, :status, :ccid, :accid)
            RETURNING *
        """), {
            "name": wc.name, "code": wc.code, "cap": wc.capacity_per_day, 
            "cost": wc.cost_per_hour, "loc": wc.location, "status": wc.status,
            "ccid": wc.cost_center_id, "accid": wc.default_expense_account_id
        }).fetchone()
        conn.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="create_work_center", resource_type="work_centers",
                     resource_id=str(new_wc.id), details={"name": wc.name, "code": wc.code},
                     request=request)
        return dict(new_wc._mapping)
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating work center: {e}")
        raise HTTPException(**http_error(400, "work_center_create_failed", request))
    finally:
        conn.close()

@router.put("/work-centers/{wc_id}", response_model=WorkCenterResponse, dependencies=[Depends(require_permission("manufacturing.manage"))])
def update_work_center(wc_id: int, wc: WorkCenterCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Update Work Center."""
    conn = get_db_connection(current_user.company_id)
    try:
        updated = conn.execute(text("""
            UPDATE work_centers 
            SET name=:name, code=:code, capacity_per_day=:cap, cost_per_hour=:cost, location=:loc, status=:status, 
                cost_center_id=:ccid, default_expense_account_id=:accid, updated_at=NOW()
            WHERE id=:id
            RETURNING *
        """), {
            "name": wc.name, "code": wc.code, "cap": wc.capacity_per_day, 
            "cost": wc.cost_per_hour, "loc": wc.location, "status": wc.status, 
            "ccid": wc.cost_center_id, "accid": wc.default_expense_account_id, "id": wc_id
        }).fetchone()
        if not updated:
            raise HTTPException(**http_error(404, "work_center_not_found", request))
        conn.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="update_work_center", resource_type="work_centers",
                     resource_id=str(wc_id), details={"name": wc.name},
                     request=request)
        return dict(updated._mapping)
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating work center {wc_id}: {e}")
        raise HTTPException(**http_error(400, "work_center_update_failed", request))
    finally:
        conn.close()

# ==========================================
# 2. ROUTINGS
# ==========================================

@router.delete("/work-centers/{wc_id}", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.delete"]))], response_model=Dict[str, Any])
def delete_work_center(wc_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Delete Work Center."""
    conn = get_db_connection(current_user.company_id)
    try:
        # Check if in use by any operations
        in_use = conn.execute(text("""
            SELECT COUNT(*) FROM manufacturing_operations WHERE work_center_id = :id AND is_deleted = false
        """), {"id": wc_id}).scalar()
        if in_use > 0:
            logger.warning(f"Cannot delete work center {wc_id}: used in {in_use} operation(s)")
            raise HTTPException(**http_error(400, "work_center_has_operations", request))
        
        result = conn.execute(text("UPDATE work_centers SET is_deleted = true, deleted_at = NOW(), updated_at = NOW() WHERE id = :id AND is_deleted = false"), {"id": wc_id})
        conn.commit()
        if result.rowcount == 0:
            raise HTTPException(**http_error(404, "work_center_not_found", request))
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="delete_work_center", resource_type="work_centers",
                     resource_id=str(wc_id), request=request)
        return {"message": i18n_message("work_center_deleted_success", request)}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting work center {wc_id}: {e}")
        raise HTTPException(**http_error(400, "work_center_delete_failed", request))
    finally:
        conn.close()



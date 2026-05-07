
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List
from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission, require_module
from utils.audit import log_activity
from utils.limiter import limiter
from schemas.cost_centers import CostCenterCreate, CostCenterUpdate, CostCenterResponse
import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cost-centers", tags=["Cost Centers"], dependencies=[Depends(require_module("accounting"))])

# --- Endpoints ---

@router.get("/", response_model=List[CostCenterResponse], dependencies=[Depends(require_permission(["accounting.view", "accounting.cost_centers.view"]))])
@limiter.limit("200/minute")
def list_cost_centers(request: Request, current_user: dict = Depends(get_current_user)):
    """List all cost centers"""
    conn = get_db_connection(current_user.company_id)
    try:
        result = conn.execute(text("""
            SELECT id, center_code, center_name, center_name_en, department_id, manager_id, is_active
            FROM cost_centers
            ORDER BY id ASC
        """)).fetchall()
        return [dict(row._mapping) for row in result]
    finally:
        conn.close()

@router.post("/", response_model=CostCenterResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("accounting.cost_centers.manage"))])
@limiter.limit("100/minute")
def create_cost_center(request: Request, cc: CostCenterCreate, current_user: dict = Depends(get_current_user)):
    """Create a new cost center"""
    conn = get_db_connection(current_user.company_id)
    try:
        # Check duplicate code
        if cc.center_code:
            existing = conn.execute(text("SELECT 1 FROM cost_centers WHERE center_code = :code"), {"code": cc.center_code}).fetchone()
            if existing:
                raise HTTPException(status_code=400, detail="Cost center code already exists")

        result = conn.execute(text("""
            INSERT INTO cost_centers (center_code, center_name, center_name_en, department_id, manager_id, is_active)
            VALUES (:code, :name, :name_en, :dept, :mgr, :active)
            RETURNING id, center_code, center_name, center_name_en, department_id, manager_id, is_active
        """), {
            "code": cc.center_code,
            "name": cc.center_name,
            "name_en": cc.center_name_en,
            "dept": cc.department_id,
            "mgr": cc.manager_id,
            "active": cc.is_active
        }).fetchone()
        conn.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="create_cost_center", resource_type="cost_center",
                     resource_id=str(result._mapping["id"]),
                     details={"code": cc.center_code, "name": cc.center_name}, request=request)
        return dict(result._mapping)
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()

@router.put("/{cc_id}", response_model=CostCenterResponse, dependencies=[Depends(require_permission("accounting.cost_centers.manage"))])
@limiter.limit("100/minute")
def update_cost_center(request: Request, cc_id: int, cc: CostCenterUpdate, current_user: dict = Depends(get_current_user)):
    """Update a cost center"""
    conn = get_db_connection(current_user.company_id)
    try:
        # Check existence
        existing = conn.execute(text("SELECT 1 FROM cost_centers WHERE id = :id"), {"id": cc_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Cost center not found")

        # Check duplicate code
        if cc.center_code:
            dup = conn.execute(text("SELECT 1 FROM cost_centers WHERE center_code = :code AND id != :id"), 
                               {"code": cc.center_code, "id": cc_id}).fetchone()
            if dup:
                raise HTTPException(status_code=400, detail="Cost center code already exists")

        # Dynamic Update
        update_fields = []
        params = {"id": cc_id}
        
        if cc.center_code is not None:
            update_fields.append("center_code = :code")
            params["code"] = cc.center_code
        if cc.center_name is not None:
            update_fields.append("center_name = :name")
            params["name"] = cc.center_name
        if cc.center_name_en is not None:
            update_fields.append("center_name_en = :name_en")
            params["name_en"] = cc.center_name_en
        if cc.department_id is not None:
            update_fields.append("department_id = :dept")
            params["dept"] = cc.department_id
        if cc.manager_id is not None:
            update_fields.append("manager_id = :mgr")
            params["mgr"] = cc.manager_id
        if cc.is_active is not None:
            update_fields.append("is_active = :active")
            params["active"] = cc.is_active

        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")

        sql = f"UPDATE cost_centers SET {', '.join(update_fields)} WHERE id = :id RETURNING id, center_code, center_name, center_name_en, department_id, manager_id, is_active"
        
        result = conn.execute(text(sql), params).fetchone()
        conn.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="update_cost_center", resource_type="cost_center",
                     resource_id=str(cc_id),
                     details={"fields": list(params.keys())}, request=request)
        return dict(result._mapping)
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()

@router.delete("/{cc_id}", dependencies=[Depends(require_permission("accounting.cost_centers.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def delete_cost_center(request: Request, cc_id: int, current_user: dict = Depends(get_current_user)):
    """Delete a cost center (if unused)"""
    conn = get_db_connection(current_user.company_id)
    try:
        # Check usage in journal lines
        usage = conn.execute(text("SELECT 1 FROM journal_lines WHERE cost_center_id = :id"), {"id": cc_id}).fetchone()
        if usage:
             raise HTTPException(status_code=400, detail="Cannot delete cost center because it is used in accounting transactions")
        
        result = conn.execute(text("DELETE FROM cost_centers WHERE id = :id"), {"id": cc_id})
        if result.rowcount == 0:
             raise HTTPException(status_code=404, detail="Cost center not found")
             
        conn.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="delete_cost_center", resource_type="cost_center",
                     resource_id=str(cc_id),
                     details={}, request=request)
        return {"message": "Cost center deleted successfully"}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()

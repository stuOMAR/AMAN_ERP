"""core sub-router — split from monolithic core.py (T6.3).

Mounted under the parent router via core/__init__.py.
"""
import logging
from decimal import Decimal
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from utils.i18n import http_error
from pydantic import BaseModel
from sqlalchemy import text
from routers.auth import get_current_user
from utils.permissions import require_permission, require_module
from database import get_db_connection
from utils.tx import transactional
from utils.accounting import get_base_currency
from utils.fiscal_lock import check_fiscal_period_open
from utils.exports import generate_excel, generate_pdf, create_export_response
from utils.audit import log_activity
from services.gl_service import create_journal_entry
from schemas import UserResponse
from schemas.manufacturing_advanced import (
    WorkCenterCreate, WorkCenterResponse,
    RouteCreate, RouteResponse,
    BOMCreate, BOMResponse,
    ProductionOrderCreate, ProductionOrderResponse,
    ProductionOrderOperationResponse, MRPPlanResponse,
    EquipmentCreate, EquipmentResponse,
    MaintenanceLogCreate, MaintenanceLogResponse
)

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/equipment", response_model=List[EquipmentResponse], dependencies=[Depends(require_permission("manufacturing.view"))])
def list_equipment(
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    current_user: UserResponse = Depends(get_current_user),
):
    """List Equipment."""
    conn = get_db_connection(current_user.company_id)
    try:
        equip = conn.execute(text("""
            SELECT e.*, wc.name as work_center_name
            FROM manufacturing_equipment e
            LEFT JOIN work_centers wc ON e.work_center_id = wc.id
            WHERE e.is_deleted = false
            ORDER BY e.id DESC
            LIMIT :limit OFFSET :offset
        """), {"limit": limit, "offset": offset}).fetchall()
        return [dict(e._mapping) for e in equip]
    finally:
        conn.close()

@router.post("/equipment", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.create"]))], response_model=Dict[str, Any])
def create_equipment(equip: EquipmentCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Create Equipment."""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        new_equip = conn.execute(text("""
            INSERT INTO manufacturing_equipment (name, code, work_center_id, status, purchase_date, last_maintenance_date, next_maintenance_date, notes)
            VALUES (:name, :code, :wcid, :status, :pdate, :lmdate, :nmdate, :notes)
            RETURNING *
        """), {
            "name": equip.name, "code": equip.code, "wcid": equip.work_center_id,
            "status": equip.status, "pdate": equip.purchase_date,
            "lmdate": equip.last_maintenance_date, "nmdate": equip.next_maintenance_date,
            "notes": equip.notes
        }).fetchone()
        
        trans.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="create_equipment", resource_type="manufacturing_equipment",
                     resource_id=str(new_equip.id), details={"name": equip.name},
                     request=request)
        return dict(new_equip._mapping)
    except HTTPException:
        raise
    except Exception as e:
        trans.rollback()
        logger.error(f"Error creating equipment: {e}")
        raise HTTPException(**http_error(400, "equipment_create_failed", request))
    finally:
        conn.close()

@router.put("/equipment/{equip_id}", response_model=EquipmentResponse, dependencies=[Depends(require_permission("manufacturing.manage"))])
def update_equipment(equip_id: int, equip: EquipmentCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Update Equipment."""
    conn = get_db_connection(current_user.company_id)
    try:
        updated = conn.execute(text("""
            UPDATE manufacturing_equipment SET name=:name, code=:code, work_center_id=:wcid, status=:status,
                purchase_date=:pdate, last_maintenance_date=:lmdate, next_maintenance_date=:nmdate, notes=:notes
            WHERE id=:id RETURNING *
        """), {
            "name": equip.name, "code": equip.code, "wcid": equip.work_center_id,
            "status": equip.status, "pdate": equip.purchase_date,
            "lmdate": equip.last_maintenance_date, "nmdate": equip.next_maintenance_date,
            "notes": equip.notes, "id": equip_id
        }).fetchone()
        if not updated:
            raise HTTPException(**http_error(404, "equipment_not_found", request))
        conn.commit()
        result = dict(updated._mapping)
        wc = conn.execute(text("SELECT name FROM work_centers WHERE id = :wid"), {"wid": equip.work_center_id}).fetchone() if equip.work_center_id else None
        result['work_center_name'] = wc.name if wc else None
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="update_equipment", resource_type="manufacturing_equipment",
                     resource_id=str(equip_id), details={"name": equip.name},
                     request=request)
        return result
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating equipment {equip_id}: {e}")
        raise HTTPException(**http_error(400, "equipment_update_failed", request))
    finally:
        conn.close()

@router.delete("/equipment/{equip_id}", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.delete"]))], response_model=Dict[str, Any])
def delete_equipment(equip_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Delete Equipment."""
    conn = get_db_connection(current_user.company_id)
    try:
        # Check for maintenance logs
        logs = conn.execute(text("SELECT COUNT(*) FROM maintenance_logs WHERE equipment_id = :id"), {"id": equip_id}).scalar()
        if logs > 0:
            logger.warning(f"Cannot delete equipment {equip_id}: has {logs} maintenance log(s)")
            raise HTTPException(**http_error(400, "equipment_has_maintenance_records", request))
        deleted = conn.execute(text("UPDATE manufacturing_equipment SET is_deleted = true, deleted_at = NOW() WHERE id = :id AND is_deleted = false RETURNING id"), {"id": equip_id}).fetchone()
        if not deleted:
            raise HTTPException(**http_error(404, "equipment_not_found", request))
        conn.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="delete_equipment", resource_type="manufacturing_equipment",
                     resource_id=str(equip_id), request=request)
        return {"detail": "Equipment deleted"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting equipment {equip_id}: {e}")
        raise HTTPException(**http_error(400, "equipment_delete_failed", request))
    finally:
        conn.close()

@router.get("/maintenance-logs", response_model=List[MaintenanceLogResponse], dependencies=[Depends(require_permission("manufacturing.view"))])
def list_maintenance_logs(
    equipment_id: Optional[int] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    current_user: UserResponse = Depends(get_current_user),
):
    """List Maintenance Logs."""
    conn = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT ml.*, e.name as equipment_name, u.full_name as performed_by_name
            FROM maintenance_logs ml
            LEFT JOIN manufacturing_equipment e ON ml.equipment_id = e.id
            LEFT JOIN company_users u ON ml.performed_by = u.id
            WHERE 1=1
        """
        params = {}
        if equipment_id:
            query += " AND ml.equipment_id = :eid"
            params["eid"] = equipment_id
            
        query += " ORDER BY ml.maintenance_date DESC LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = offset
        
        logs = conn.execute(text(query), params).fetchall()
        return [dict(l._mapping) for l in logs]
    finally:
        conn.close()

@router.post("/maintenance-logs", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.create"]))], response_model=Dict[str, Any])
def create_maintenance_log(log: MaintenanceLogCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Create Maintenance Log."""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        new_log = conn.execute(text("""
            INSERT INTO maintenance_logs (equipment_id, maintenance_type, description, cost, performed_by, 
                                        external_service_provider, maintenance_date, next_due_date, status, notes)
            VALUES (:eid, :mtype, :desc, :cost, :uid, :ext, :mdate, :ndate, :status, :notes)
            RETURNING *
        """), {
            "eid": log.equipment_id, "mtype": log.maintenance_type, "desc": log.description,
            "cost": log.cost, "uid": log.performed_by, "ext": log.external_service_provider,
            "mdate": log.maintenance_date, "ndate": log.next_due_date,
            "status": log.status, "notes": log.notes
        }).fetchone()
        
        # Update Equipment dates if necessary
        if log.maintenance_date:
            conn.execute(text("UPDATE manufacturing_equipment SET last_maintenance_date = :date WHERE id = :id"), 
                         {"date": log.maintenance_date, "id": log.equipment_id})
        
        if log.next_due_date:
             conn.execute(text("UPDATE manufacturing_equipment SET next_maintenance_date = :date WHERE id = :id"), 
                         {"date": log.next_due_date, "id": log.equipment_id})

        trans.commit()
        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="create_maintenance_log", resource_type="maintenance_logs",
                     resource_id=str(new_log.id), details={"equipment_id": log.equipment_id, "type": log.maintenance_type},
                     request=request)
        # Fetch updated log with joins
        log_res = conn.execute(text("""
            SELECT ml.*, e.name as equipment_name, u.full_name as performed_by_name
            FROM maintenance_logs ml
            LEFT JOIN manufacturing_equipment e ON ml.equipment_id = e.id
            LEFT JOIN company_users u ON ml.performed_by = u.id
            WHERE ml.id = :lid
        """), {"lid": new_log.id}).fetchone()
        
        return dict(log_res._mapping)
    except HTTPException:
        raise
    except Exception as e:
        trans.rollback()
        logger.error(f"Error creating maintenance log: {e}")
        raise HTTPException(**http_error(400, "maintenance_record_create_failed", request))
    finally:
        conn.close()


# ==========================================
# 7. MANUFACTURING REPORTS
# ==========================================


"""projects sub-router — split from monolithic projects.py (T6.3).

Mounted under the parent router via projects/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, File, UploadFile
from utils.i18n import http_error, i18n_message
import os
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, validate_branch_access, require_module
from utils.accounting import (
    generate_sequential_number, get_mapped_account_id,
    get_base_currency, compute_line_amounts, compute_invoice_totals
)
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from sqlalchemy import text
from services.gl_service import create_journal_entry as gl_create_journal_entry
import logging

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

from schemas.projects import (
    ProjectCreate, ProjectUpdate, TaskCreate, TaskUpdate,
    ProjectExpenseCreate, ProjectRevenueCreate,
    TimesheetCreate, TimesheetUpdate, TimesheetApprove,
    ProjectInvoiceCreate, ChangeOrderCreate, ChangeOrderUpdate, ProjectCloseRequest,
    ProjectRiskCreate, ProjectRiskUpdate, TaskDependencyCreate
)
from schemas.timetracking import (
    TimesheetEntryCreate, TimesheetEntryUpdate,
    WeeklySubmitRequest, RejectRequest
)
from schemas.resource import AllocationCreate, AllocationUpdate

router = APIRouter()

from .core import _D2, _D4

@router.get("/{project_id}/change-orders", dependencies=[Depends(require_permission("projects.view"))], response_model=List[Dict[str, Any]])
async def get_change_orders(project_id: int, current_user: dict = Depends(get_current_user)):
    """جلب أوامر التغيير للمشروع"""
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("""
            SELECT co.*,
                   COALESCE(req.full_name, '') as requested_by_name,
                   COALESCE(app.full_name, '') as approved_by_name
            FROM project_change_orders co
            LEFT JOIN company_users req ON co.requested_by = req.id
            LEFT JOIN company_users app ON co.approved_by = app.id
            WHERE co.project_id = :pid
            ORDER BY co.created_at DESC
        """), {"pid": project_id}).fetchall()
        return [dict(r._mapping) for r in result]
    finally:
        db.close()


@router.post("/{project_id}/change-orders", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def create_change_order(
    project_id: int,
    co: ChangeOrderCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء أمر تغيير جديد"""
    db = get_db_connection(current_user.company_id)
    try:
        project = db.execute(text("SELECT * FROM projects WHERE id = :id"), {"id": project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(404, "project_not_found"))

        co_num = generate_sequential_number(db, f"CO-{datetime.now().year}", "project_change_orders", "change_order_number")

        co_id = db.execute(text("""
            INSERT INTO project_change_orders (
                project_id, change_order_number, title, description,
                change_type, cost_impact, time_impact_days, status, requested_by
            ) VALUES (:pid, :num, :title, :desc, :type, :cost, :days, 'pending', :uid)
            RETURNING id
        """), {
            "pid": project_id, "num": co_num, "title": co.title,
            "desc": co.description, "type": co.change_type,
            "cost": co.cost_impact, "days": co.time_impact_days,
            "uid": current_user.id
        }).scalar()

        db.commit()

        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.change_order.create", resource_type="project_change_order",
            resource_id=str(co_id),
            details={"project_id": project_id, "cost_impact": co.cost_impact, "title": co.title},
            request=request
        )

        return {"success": True, "id": co_id, "change_order_number": co_num}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating change order: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/change-orders/{co_id}", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def update_change_order(
    co_id: int,
    data: ChangeOrderUpdate,
    current_user: dict = Depends(get_current_user)
):
    """تحديث أمر تغيير"""
    db = get_db_connection(current_user.company_id)
    try:
        existing = db.execute(text("SELECT * FROM project_change_orders WHERE id = :id"), {"id": co_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "change_order_not_found"))
        if existing.status == 'approved':
            raise HTTPException(status_code=400, detail=i18n_message("change_order_cannot_edit_after_approval"))

        updates = []
        params = {"id": co_id}
        for field in ["title", "description", "change_type", "cost_impact", "time_impact_days", "status"]:
            val = getattr(data, field, None)
            if val is not None:
                updates.append(f"{field} = :{field}")
                params[field] = val
        updates.append("updated_at = NOW()")

        if not updates:
            raise HTTPException(**http_error(400, "no_data_to_update"))

        db.execute(text(f"UPDATE project_change_orders SET {', '.join(updates)} WHERE id = :id"), params)
        db.commit()
        return {"success": True, "message": i18n_message("change_order_updated_success")}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating change order: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.post("/change-orders/{co_id}/approve", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def approve_change_order(
    co_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """الموافقة على أمر التغيير وتعديل ميزانية المشروع تلقائياً"""
    db = get_db_connection(current_user.company_id)
    try:
        co = db.execute(text("SELECT * FROM project_change_orders WHERE id = :id"), {"id": co_id}).fetchone()
        if not co:
            raise HTTPException(**http_error(404, "change_order_not_found"))
        if co.status != 'pending':
            raise HTTPException(status_code=400, detail=i18n_message("change_order_approve_invalid_status", status=co.status))

        db.execute(text("""
            UPDATE project_change_orders
            SET status = 'approved', approved_by = :uid, approved_at = NOW(), updated_at = NOW()
            WHERE id = :id
        """), {"id": co_id, "uid": current_user.id})

        if co.cost_impact:
            db.execute(text("""
                UPDATE projects
                SET planned_budget = COALESCE(planned_budget, 0) + :cost, updated_at = NOW()
                WHERE id = :pid
            """), {"cost": co.cost_impact, "pid": co.project_id})

        if co.time_impact_days and co.time_impact_days > 0:
            db.execute(text("""
                UPDATE projects
                SET end_date = COALESCE(end_date, CURRENT_DATE) + :days * INTERVAL '1 day', updated_at = NOW()
                WHERE id = :pid
            """), {"days": co.time_impact_days, "pid": co.project_id})

        db.commit()

        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.change_order.approve", resource_type="project_change_order",
            resource_id=str(co_id),
            details={"project_id": co.project_id, "cost_impact": float(co.cost_impact or 0)},
            request=request
        )

        return {"success": True, "message": i18n_message("change_order_approved_and_budget_updated")}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error approving change order: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# Project Closure with P&L Journal Entry
# ═══════════════════════════════════════════════════════════


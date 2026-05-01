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

@router.get("/{project_id}/risks", dependencies=[Depends(require_permission("projects.view"))], response_model=List[Dict[str, Any]])
def list_project_risks(project_id: int, current_user=Depends(get_current_user)):
    """سجل المخاطر"""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT pr.*, cu.full_name as owner_name
            FROM project_risks pr
            LEFT JOIN company_users cu ON cu.id = pr.owner_id
            WHERE pr.project_id = :pid
            ORDER BY pr.risk_score DESC NULLS LAST, pr.created_at DESC
        """), {"pid": project_id}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.post("/{project_id}/risks", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
def create_project_risk(project_id: int, risk: ProjectRiskCreate, request: Request, current_user=Depends(get_current_user)):
    """إضافة خطر"""
    db = get_db_connection(current_user.company_id)
    try:
        _RISK_WEIGHT = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        score = _RISK_WEIGHT.get(risk.probability, 2) * _RISK_WEIGHT.get(risk.impact, 2)
        result = db.execute(text("""
            INSERT INTO project_risks (project_id, title, description, probability,
                impact, risk_score, status, mitigation_plan, owner_id, due_date)
            VALUES (:pid, :t, :d, :p, :i, :s, :st, :mp, :oid, :dd)
            RETURNING id
        """), {
            "pid": project_id, "t": risk.title, "d": risk.description,
            "p": risk.probability, "i": risk.impact, "s": score,
            "st": risk.status, "mp": risk.mitigation_plan,
            "oid": risk.owner_id, "dd": risk.due_date
        })
        risk_id = result.fetchone()[0]
        db.commit()
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.risk_create", resource_type="project_risk",
            resource_id=str(risk_id),
            details={"project_id": project_id, "title": risk.title},
            request=request
        )
        return {"id": risk_id, "message": i18n_message("risk_created_success")}
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating project risk: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/risks/{risk_id}", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
def update_project_risk(risk_id: int, risk: ProjectRiskUpdate, request: Request, current_user=Depends(get_current_user)):
    """تحديث خطر"""
    db = get_db_connection(current_user.company_id)
    try:
        # Build dynamic SET clause from non-None fields
        _RISK_WEIGHT = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        set_parts = []
        params = {"id": risk_id}
        fields = {
            "title": risk.title, "description": risk.description,
            "probability": risk.probability, "impact": risk.impact,
            "status": risk.status, "mitigation_plan": risk.mitigation_plan,
            "owner_id": risk.owner_id, "due_date": risk.due_date
        }
        for field, value in fields.items():
            if value is not None:
                set_parts.append(f"{field} = :{field}")
                params[field] = value

        # Recalculate risk_score if probability or impact changed
        if risk.probability is not None or risk.impact is not None:
            # Get current values for any not provided
            current = db.execute(text("SELECT probability, impact FROM project_risks WHERE id = :id"), {"id": risk_id}).fetchone()
            if current:
                prob = risk.probability or current.probability
                imp = risk.impact or current.impact
                score = _RISK_WEIGHT.get(prob, 2) * _RISK_WEIGHT.get(imp, 2)
                set_parts.append("risk_score = :risk_score")
                params["risk_score"] = score

        if set_parts:
            set_parts.append("updated_at = CURRENT_TIMESTAMP")
            query = f"UPDATE project_risks SET {', '.join(set_parts)} WHERE id = :id"
            db.execute(text(query), params)

        db.commit()
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.risk_update", resource_type="project_risk",
            resource_id=str(risk_id),
            details={"risk_id": risk_id},
            request=request
        )
        return {"message": i18n_message("risk_updated_success")}
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating project risk: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.delete("/risks/{risk_id}", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
def delete_project_risk(risk_id: int, request: Request, current_user=Depends(get_current_user)):
    """حذف خطر"""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("DELETE FROM project_risks WHERE id = :id"), {"id": risk_id})
        db.commit()
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.risk_delete", resource_type="project_risk",
            resource_id=str(risk_id),
            details={"risk_id": risk_id},
            request=request
        )
        return {"message": i18n_message("risk_deleted_success")}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting project risk: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ===================== B5: Task Dependencies =====================


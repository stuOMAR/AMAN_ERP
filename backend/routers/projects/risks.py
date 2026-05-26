"""projects sub-router — split from monolithic projects.py (T6.3).

Mounted under the parent router via projects/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error, i18n_message
from typing import Any, Dict, List
from decimal import Decimal
from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission, validate_branch_access
from utils.audit import log_activity
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

from schemas.projects import (  # noqa: E402
    ProjectRiskCreate, ProjectRiskUpdate
)

router = APIRouter()



def _validate_project_access(db, project_id: int, current_user):
    project = db.execute(
        text("SELECT id, branch_id FROM projects WHERE id = :id"),
        {"id": project_id},
    ).fetchone()
    if not project:
        raise HTTPException(**http_error(404, "project_not_found"))
    validate_branch_access(current_user, project.branch_id)
    return project


def _validate_risk_access(db, risk_id: int, current_user):
    risk = db.execute(text("""
        SELECT pr.id, pr.project_id, p.branch_id
        FROM project_risks pr
        JOIN projects p ON p.id = pr.project_id
        WHERE pr.id = :id
    """), {"id": risk_id}).fetchone()
    if not risk:
        raise HTTPException(**http_error(404, "risk_not_found"))
    validate_branch_access(current_user, risk.branch_id)
    return risk


@router.get("/{project_id}/risks", dependencies=[Depends(require_permission("projects.view"))], response_model=List[Dict[str, Any]])
def list_project_risks(project_id: int, current_user=Depends(get_current_user)):
    """سجل المخاطر"""
    db = get_db_connection(current_user.company_id)
    try:
        _validate_project_access(db, project_id, current_user)
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
        _validate_project_access(db, project_id, current_user)
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
        _validate_risk_access(db, risk_id, current_user)
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
        _validate_risk_access(db, risk_id, current_user)
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

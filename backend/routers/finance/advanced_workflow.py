"""
AMAN ERP - Advanced Workflow Engine
سير العمل المتقدم: شروط، SLA، تصعيد، موافقة تلقائية
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
import logging
import json
from datetime import date

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission
from utils.audit import log_activity
from utils.limiter import limiter
from utils.fiscal_lock import check_fiscal_period_open

router = APIRouter(prefix="/workflow", tags=["Advanced Workflow"])
logger = logging.getLogger(__name__)


class WorkflowSLAUpdate(BaseModel):
    sla_hours: int = 48
    escalation_to: Optional[int] = None
    auto_approve_below: Optional[float] = None
    allow_parallel: bool = False


@router.get("/advanced/{workflow_id}", dependencies=[Depends(require_permission("approvals.view"))], response_model=Dict[str, Any])
@limiter.limit("200/minute")
def get_advanced_workflow(request: Request, workflow_id: int, current_user=Depends(get_current_user)):
    """عرض سير العمل المتقدم مع الشروط وSLA"""
    db = get_db_connection(current_user.company_id)
    try:
        wf = db.execute(text("""
            SELECT aw.*,
                   COALESCE(aw.conditions, '[]') as conditions,
                   COALESCE(aw.sla_hours, 48) as sla_hours,
                   aw.escalation_to, aw.allow_parallel, aw.auto_approve_below,
                   eu.full_name as escalation_user_name
            FROM approval_workflows aw
            LEFT JOIN company_users eu ON aw.escalation_to = eu.id
            WHERE aw.id = :id
        """), {"id": workflow_id}).fetchone()
        if not wf:
            raise HTTPException(**http_error(404, "workflow_not_found", request))

        result = dict(wf._mapping)
        if isinstance(result.get("conditions"), str):
            result["conditions"] = json.loads(result["conditions"])
        return result
    finally:
        db.close()


@router.put("/advanced/{workflow_id}/conditions",
            dependencies=[Depends(require_permission("approvals.edit"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def update_workflow_conditions(
    request: Request,
    workflow_id: int,
    conditions: list,
    current_user=Depends(get_current_user)
):
    """تحديث شروط التوجيه لسير العمل"""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("""
            UPDATE approval_workflows SET conditions = :conds WHERE id = :id
        """), {"conds": json.dumps(conditions), "id": workflow_id})
        db.commit()
        return {"message": i18n_message("conditions_updated", request)}
    finally:
        db.close()


@router.put("/advanced/{workflow_id}/sla",
            dependencies=[Depends(require_permission("approvals.edit"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def update_workflow_sla(
    request: Request,
    workflow_id: int,
    data: WorkflowSLAUpdate,
    current_user=Depends(get_current_user)
):
    """تحديث إعدادات SLA والتصعيد"""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("""
            UPDATE approval_workflows
            SET sla_hours = :sla, escalation_to = :esc,
                auto_approve_below = :auto, allow_parallel = :parallel
            WHERE id = :id
        """), {
            "sla": data.sla_hours, "esc": data.escalation_to,
            "auto": data.auto_approve_below, "parallel": data.allow_parallel,
            "id": workflow_id
        })
        db.commit()
        return {"message": i18n_message("sla_settings_updated", request)}
    finally:
        db.close()


@router.post("/check-escalation", dependencies=[Depends(require_permission("approvals.view"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def check_sla_escalations(request: Request, current_user=Depends(get_current_user)):
    """فحص الطلبات المتأخرة وتصعيدها"""
    db = get_db_connection(current_user.company_id)
    try:
        overdue = db.execute(text("""
            SELECT ar.id, ar.document_type, ar.document_id,
                   aw.sla_hours, aw.escalation_to,
                   EXTRACT(EPOCH FROM (NOW() - ar.created_at)) / 3600 as hours_waiting
            FROM approval_requests ar
            JOIN approval_workflows aw ON ar.workflow_id = aw.id
            WHERE ar.status = 'pending'
              AND aw.sla_hours IS NOT NULL
              AND EXTRACT(EPOCH FROM (NOW() - ar.created_at)) / 3600 > aw.sla_hours
        """)).fetchall()

        escalated = 0
        for req in overdue:
            r = dict(req._mapping)
            if r.get("escalation_to"):
                db.execute(text("""
                    UPDATE approval_requests
                    SET current_approver_id = :esc, status = 'escalated'
                    WHERE id = :id
                """), {"esc": r["escalation_to"], "id": r["id"]})
                escalated += 1
                log_activity(db, user_id=current_user.id, username=current_user.username,
                             action="workflow.escalate", resource_type="approval_request",
                             resource_id=str(r["id"]),
                             details={"escalated_to": r["escalation_to"],
                                      "hours_waiting": round(r["hours_waiting"], 2),
                                      "sla_hours": r["sla_hours"]},
                             request=request)

        db.commit()
        return {
            "checked": len(overdue),
            "escalated": escalated,
            "message": i18n_message("escalated_requests", request)
        }
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.post("/auto-approve", dependencies=[Depends(require_permission("approvals.edit"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def auto_approve_below_threshold(request: Request, current_user=Depends(get_current_user)):
    """الموافقة التلقائية على الطلبات تحت الحد الأدنى"""
    db = get_db_connection(current_user.company_id)
    try:
        # Audit F-NEW-012: bulk approval is a dated mutation; reject if
        # today's period is locked. Canonical guard (C-ARCH-002).
        check_fiscal_period_open(db, date.today(), request=request)

        auto_approved = db.execute(text("""
            UPDATE approval_requests ar
            SET status = 'approved', action_date = NOW(),
                action_notes = 'موافقة تلقائية - تحت الحد الأدنى'
            FROM approval_workflows aw
            WHERE ar.workflow_id = aw.id
              AND ar.status = 'pending'
              AND aw.auto_approve_below IS NOT NULL
              AND ar.amount <= aw.auto_approve_below
            RETURNING ar.id
        """)).fetchall()

        db.commit()
        for approved in auto_approved:
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="workflow.auto_approve", resource_type="approval_request",
                         resource_id=str(approved[0]),
                         details={"reason": "below_threshold"},
                         request=request)
        return {
            "auto_approved": len(auto_approved),
            "message": i18n_message("auto_approved_requests", request)
        }
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/analytics", dependencies=[Depends(require_permission("approvals.view"))], response_model=Dict[str, Any])
@limiter.limit("200/minute")
def workflow_analytics(request: Request, current_user=Depends(get_current_user)):
    """تحليلات سير العمل"""
    db = get_db_connection(current_user.company_id)
    try:
        stats = db.execute(text("""
            SELECT
                COUNT(*) as total_requests,
                COUNT(*) FILTER (WHERE status = 'pending') as pending,
                COUNT(*) FILTER (WHERE status = 'approved') as approved,
                COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
                COUNT(*) FILTER (WHERE status = 'escalated') as escalated,
                COALESCE(AVG(EXTRACT(EPOCH FROM (action_date - created_at)) / 3600)
                    FILTER (WHERE action_date IS NOT NULL), 0) as avg_approval_hours
            FROM approval_requests
        """)).fetchone()

        by_type = db.execute(text("""
            SELECT document_type,
                   COUNT(*) as total,
                   COUNT(*) FILTER (WHERE status = 'approved') as approved,
                   COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
                   COALESCE(AVG(EXTRACT(EPOCH FROM (action_date - created_at)) / 3600)
                       FILTER (WHERE action_date IS NOT NULL), 0) as avg_hours
            FROM approval_requests
            GROUP BY document_type
            ORDER BY total DESC
        """)).fetchall()

        return {
            "summary": dict(stats._mapping) if stats else {},
            "by_document_type": [dict(r._mapping) for r in by_type]
        }
    finally:
        db.close()

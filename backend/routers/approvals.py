"""
Approval Workflows Router - WF-001, WF-002, WF-003
سلسلة اعتمادات متعددة المستويات
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from routers.auth import get_current_user
from utils.tx import transactional
from utils.audit import log_activity
from utils.permissions import require_permission, require_module
from utils.tax_precision import require_idempotency_key
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/approvals", tags=["Approvals"], dependencies=[Depends(require_module("approvals"))])


# ===================== Schemas =====================

class ApprovalStepSchema(BaseModel):
    step: int
    approver_role: str  # role slug or 'specific_user'
    approver_user_id: Optional[int] = None
    label: str = ""  # e.g. "مدير القسم", "المدير المالي"

class WorkflowCreateSchema(BaseModel):
    name: str
    document_type: str  # purchase_order, expense, leave_request, payment_voucher
    description: Optional[str] = None
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    steps: List[ApprovalStepSchema]
    is_active: bool = True

class ApprovalRequestCreate(BaseModel):
    document_type: str
    document_id: int
    amount: Decimal
    description: Optional[str] = None

class ApprovalActionSchema(BaseModel):
    action: str  # approve, reject, return
    notes: Optional[str] = None


# ===================== Workflows CRUD =====================

@router.get("/workflows", dependencies=[Depends(require_permission("settings.view"))], response_model=List[Dict[str, Any]])
def list_workflows(
    document_type: Optional[str] = None,
    current_user=Depends(get_current_user)
):
    """قائمة سلاسل الاعتماد"""
    with transactional(current_user.company_id) as db:
        try:
            conditions = []
            params = {}
            if document_type:
                conditions.append("document_type = :doc_type")
                params["doc_type"] = document_type
    
            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = db.execute(text(f"""
                SELECT * FROM approval_workflows {where}
                ORDER BY created_at DESC
            """), params).fetchall()
    
            return [dict(r._mapping) for r in rows]
        except Exception:
            logger.error("Error listing workflows")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/workflows/{workflow_id}", dependencies=[Depends(require_permission("settings.view"))], response_model=Dict[str, Any])
def get_workflow(workflow_id: int, request: Request, current_user=Depends(get_current_user)):
    """تفاصيل سلسلة اعتماد"""
    with transactional(current_user.company_id) as db:
        try:
            row = db.execute(text("SELECT * FROM approval_workflows WHERE id = :id"), {"id": workflow_id}).fetchone()
            if not row:
                raise HTTPException(**http_error(404, "approval_chain_not_found", request))
            return dict(row._mapping)
        except HTTPException:
            raise
        except Exception:
            logger.error("Error getting workflow")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/workflows", dependencies=[Depends(require_permission(["settings.create", "approvals.manage"]))], response_model=Dict[str, Any])
def create_workflow(data: WorkflowCreateSchema, request: Request, current_user=Depends(get_current_user)):
    """إنشاء سلسلة اعتماد جديدة"""
    with transactional(current_user.company_id) as db:
        try:
            if not data.steps:
                raise HTTPException(**http_error(400, "approval_chain_min_one_step", request))
    
            import json
            conditions = {}
            if data.min_amount is not None:
                conditions["min_amount"] = str(data.min_amount)
            if data.max_amount is not None:
                conditions["max_amount"] = str(data.max_amount)
    
            steps_json = [s.dict() for s in data.steps]
    
            result = db.execute(text("""
                INSERT INTO approval_workflows (name, document_type, description, conditions, steps, is_active, created_by)
                VALUES (:name, :doc_type, :desc, :conditions, :steps, :active, :uid)
                RETURNING id
            """), {
                "name": data.name,
                "doc_type": data.document_type,
                "desc": data.description,
                "conditions": json.dumps(conditions),
                "steps": json.dumps(steps_json),
                "active": data.is_active,
                "uid": current_user.id
            }).fetchone()
    
            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action="create", resource_type="approval_workflows",
                resource_id=str(result.id), details={"name": data.name},
                request=request, critical=True
            )
            return {"id": result.id, "message": i18n_message("approval_chain_created", request)}
        except HTTPException:
            raise
        except Exception:
            logger.error("Error creating workflow")
            raise HTTPException(**http_error(500, "internal_error"))


@router.put("/workflows/{workflow_id}", dependencies=[Depends(require_permission(["settings.edit", "approvals.manage"]))], response_model=Dict[str, Any])
def update_workflow(workflow_id: int, data: WorkflowCreateSchema, request: Request, current_user=Depends(get_current_user)):
    """تحديث سلسلة اعتماد"""
    with transactional(current_user.company_id) as db:
        try:
            existing = db.execute(text("SELECT id FROM approval_workflows WHERE id = :id"), {"id": workflow_id}).fetchone()
            if not existing:
                raise HTTPException(**http_error(404, "approval_chain_not_found", request))
    
            import json
            conditions = {}
            if data.min_amount is not None:
                conditions["min_amount"] = str(data.min_amount)
            if data.max_amount is not None:
                conditions["max_amount"] = str(data.max_amount)
    
            steps_json = [s.dict() for s in data.steps]
    
            db.execute(text("""
                UPDATE approval_workflows
                SET name = :name, document_type = :doc_type, description = :desc,
                    conditions = :conditions, steps = :steps, is_active = :active,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {
                "id": workflow_id,
                "name": data.name,
                "doc_type": data.document_type,
                "desc": data.description,
                "conditions": json.dumps(conditions),
                "steps": json.dumps(steps_json),
                "active": data.is_active
            })

            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action="update", resource_type="approval_workflows",
                resource_id=str(workflow_id),
                details={"name": data.name, "document_type": data.document_type},
                request=request, critical=True
            )
    
            return {"message": i18n_message("approval_chain_updated", request)}
        except HTTPException:
            raise
        except Exception:
            logger.error("Error updating workflow")
            raise HTTPException(**http_error(500, "internal_error"))


@router.delete("/workflows/{workflow_id}", dependencies=[Depends(require_permission(["settings.delete", "approvals.manage"]))], response_model=Dict[str, Any])
def delete_workflow(workflow_id: int, request: Request, current_user=Depends(get_current_user)):
    """حذف سلسلة اعتماد"""
    with transactional(current_user.company_id) as db:
        try:
            # Check if there are pending requests using this workflow
            pending = db.execute(text("""
                SELECT COUNT(*) FROM approval_requests WHERE workflow_id = :id AND status = 'pending'
            """), {"id": workflow_id}).scalar()
            if pending and pending > 0:
                raise HTTPException(**http_error(400, "approval_chain_has_pending_requests", request, pending=pending))
    
            db.execute(text("DELETE FROM approval_actions WHERE request_id IN (SELECT id FROM approval_requests WHERE workflow_id = :id)"), {"id": workflow_id})
            db.execute(text("DELETE FROM approval_requests WHERE workflow_id = :id"), {"id": workflow_id})
            db.execute(text("DELETE FROM approval_workflows WHERE id = :id"), {"id": workflow_id})
            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action="delete", resource_type="approval_workflows",
                resource_id=str(workflow_id),
                details={"pending_requests": pending or 0},
                request=request, critical=True
            )
            return {"message": i18n_message("approval_chain_deleted", request)}
        except HTTPException:
            raise
        except Exception:
            logger.error("Error deleting workflow")
            raise HTTPException(**http_error(500, "internal_error"))


# ===================== Approval Requests =====================

def _find_matching_workflow(db, document_type: str, amount: Decimal = Decimal(0)):
    """Find the best matching workflow for a document type and amount."""
    import json
    workflows = db.execute(text("""
        SELECT * FROM approval_workflows
        WHERE document_type = :doc_type AND is_active = TRUE
        ORDER BY created_at DESC
    """), {"doc_type": document_type}).fetchall()

    for wf in workflows:
        conditions = wf.conditions if isinstance(wf.conditions, dict) else json.loads(wf.conditions or "{}")
        min_amt = Decimal(str(conditions.get("min_amount", 0) or 0))
        max_amt_raw = conditions.get("max_amount")
        max_amt = Decimal(str(max_amt_raw)) if max_amt_raw not in (None, "") else None

        if amount >= min_amt and (max_amt is None or amount <= max_amt):
            return wf
    return None


def _create_notification(db, user_id: int, title: str, message: str, link: str = None):
    """Helper to create a notification."""
    try:
        db.execute(text("""
            INSERT INTO notifications (user_id, title, message, link, is_read, type, created_at)
            VALUES (:uid, :title, :msg, :link, FALSE, 'approval', CURRENT_TIMESTAMP)
        """), {"uid": user_id, "title": title, "msg": message, "link": link})
        from services.notifications.dispatcher import dispatch_user_notification

        tenant_id = db.execute(text("""
            SELECT CASE
                     WHEN current_database() ~ '^aman_[0-9]+$'
                     THEN regexp_replace(current_database(), '^aman_', '')::BIGINT
                     ELSE 0
                   END
        """)).scalar() or 0
        dispatch_user_notification(
            db,
            tenant_id=tenant_id,
            recipient_id=user_id,
            event_type="approval.notification",
            channel="in_app",
            title=title,
            body=message,
            feature_source="approvals",
            reference_type="approval",
            link=link,
            commit=False,
        )
    except Exception:
        logger.warning("Failed to create approval notification")


def _step_approver_user_id(step_info: dict) -> Optional[int]:
    raw_user_id = step_info.get("approver_user_id") if isinstance(step_info, dict) else None
    if raw_user_id in (None, ""):
        return None
    try:
        return int(raw_user_id)
    except (TypeError, ValueError):
        return None


def _user_can_approve_step(current_user, step_info: dict) -> bool:
    approver_user_id = _step_approver_user_id(step_info)
    if approver_user_id is not None:
        return int(getattr(current_user, "id", 0) or 0) == approver_user_id

    approver_role = str((step_info or {}).get("approver_role") or "").strip()
    if not approver_role or approver_role == "specific_user":
        return False
    return str(getattr(current_user, "role", "") or "") == approver_role


def _find_approvers_for_step(db, step_info: dict):
    approver_user_id = _step_approver_user_id(step_info)
    if approver_user_id is not None:
        return db.execute(text("""
            SELECT id FROM company_users
            WHERE id = :uid AND is_active = TRUE
        """), {"uid": approver_user_id}).fetchall()

    approver_role = str((step_info or {}).get("approver_role") or "").strip()
    if not approver_role or approver_role == "specific_user":
        return []
    return db.execute(text("""
        SELECT id FROM company_users
        WHERE role = :role AND is_active = TRUE
    """), {"role": approver_role}).fetchall()


APPROVER_ELIGIBILITY_SQL = """
AND (
    (
        NULLIF(aw.steps -> (ar.current_step - 1) ->> 'approver_user_id', '') IS NOT NULL
        AND NULLIF(aw.steps -> (ar.current_step - 1) ->> 'approver_user_id', '') ~ '^[0-9]+$'
        AND CAST(NULLIF(aw.steps -> (ar.current_step - 1) ->> 'approver_user_id', '') AS INTEGER) = :uid
    )
    OR (
        COALESCE(aw.steps -> (ar.current_step - 1) ->> 'approver_role', '') = :user_role
    )
)
"""


@router.post("/requests", dependencies=[Depends(require_permission("approvals.create"))], response_model=Dict[str, Any])
def create_approval_request(data: ApprovalRequestCreate, request: Request, current_user=Depends(get_current_user)):
    """
    إنشاء طلب اعتماد جديد.
    يُستدعى عند إنشاء أمر شراء أو مصروف أو طلب إجازة.
    """
    with transactional(current_user.company_id) as db:
        try:
            document_type = data.document_type
            document_id = data.document_id
            amount = data.amount
            description = data.description or ""
    
            # Find matching workflow
            workflow = _find_matching_workflow(db, document_type, amount)
            if not workflow:
                raise HTTPException(**http_error(404, "approval_chain_not_found_for_document", request, document_type=document_type, amount=amount))
    
            # T017: Validate workflow has steps
            import json as _json
            _steps = workflow.steps if isinstance(workflow.steps, list) else _json.loads(workflow.steps or "[]")
            if not _steps:
                raise HTTPException(**http_error(400, "workflow_misconfigured_no_steps", request))
    
            result = db.execute(text("""
                INSERT INTO approval_requests (workflow_id, document_type, document_id, amount, description,
                                              current_step, total_steps, status, requested_by)
                VALUES (:wf_id, :doc_type, :doc_id, :amount, :desc, 1, :total, 'pending', :uid)
                RETURNING id
            """), {
                "wf_id": workflow.id,
                "doc_type": document_type,
                "doc_id": document_id,
                "amount": amount,
                "desc": description,
                "total": len(_steps),
                "uid": current_user.id
            }).fetchone()
    
            # Notify first approver
            import json
            steps = workflow.steps if isinstance(workflow.steps, list) else json.loads(workflow.steps or "[]")
            if steps:
                first_step = steps[0]
                step_label = first_step.get("label", "الخطوة 1")
    
                approvers = _find_approvers_for_step(db, first_step)
    
                for approver in approvers:
                    _create_notification(db, approver.id,
                                        f"طلب اعتماد جديد - {step_label}",
                                        f"{description or document_type} بمبلغ {amount}",
                                        f"/approvals/{result.id}")

            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action="create", resource_type="approval_requests",
                resource_id=str(result.id),
                details={
                    "document_type": document_type,
                    "document_id": document_id,
                    "workflow_id": workflow.id,
                },
                request=request, critical=True
            )
    
            return {"id": result.id, "message": i18n_message("approval_request_created", request)}
        except HTTPException:
            raise
        except Exception:
            logger.error("Error creating approval request")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/pending", dependencies=[Depends(require_permission("approvals.view"))], response_model=Dict[str, Any])
def list_pending_approvals(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    document_type: Optional[str] = None,
    current_user=Depends(get_current_user)
):
    """الاعتمادات المعلقة التي تحتاج موافقة المستخدم الحالي"""
    with transactional(current_user.company_id) as db:
        try:
            offset = (page - 1) * limit
    
            conditions = ["ar.status = 'pending'"]
            params = {
                "uid": current_user.id,
                "user_role": getattr(current_user, "role", "") or "",
                "limit": limit,
                "offset": offset,
            }
    
            if document_type:
                conditions.append("ar.document_type = :doc_type")
                params["doc_type"] = document_type
    
            where = "WHERE " + " AND ".join(conditions)
            where_with_approver = f"{where}\n{APPROVER_ELIGIBILITY_SQL}"
    
            total = db.execute(text(f"""
                SELECT COUNT(*) FROM approval_requests ar
                JOIN approval_workflows aw ON ar.workflow_id = aw.id
                {where_with_approver}
            """), params).scalar() or 0
    
            rows = db.execute(text(f"""
                SELECT ar.*, aw.name as workflow_name, aw.steps as workflow_steps,
                       cu.username as requested_by_name
                FROM approval_requests ar
                JOIN approval_workflows aw ON ar.workflow_id = aw.id
                LEFT JOIN company_users cu ON ar.requested_by = cu.id
                {where_with_approver}
                ORDER BY ar.created_at DESC
                LIMIT :limit OFFSET :offset
            """), params).fetchall()
    
            items = []
            for r in rows:
                item = dict(r._mapping)
                # Convert datetime objects to strings
                for k in ["created_at", "updated_at", "completed_at"]:
                    if k in item and item[k]:
                        item[k] = str(item[k])
                items.append(item)
    
            return {"items": items, "total": total, "page": page}
        except Exception:
            logger.error("Error listing pending approvals")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/requests", dependencies=[Depends(require_permission("approvals.view"))], response_model=Dict[str, Any])
def list_all_requests(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[str] = None,
    document_type: Optional[str] = None,
    current_user=Depends(get_current_user)
):
    """جميع طلبات الاعتماد"""
    with transactional(current_user.company_id) as db:
        try:
            offset = (page - 1) * limit
            conditions = []
            params = {"limit": limit, "offset": offset}
    
            if status:
                conditions.append("ar.status = :status")
                params["status"] = status
            if document_type:
                conditions.append("ar.document_type = :doc_type")
                params["doc_type"] = document_type
    
            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    
            total = db.execute(text(f"""
                SELECT COUNT(*) FROM approval_requests ar {where}
            """), params).scalar() or 0
    
            rows = db.execute(text(f"""
                SELECT ar.*, aw.name as workflow_name,
                       cu.username as requested_by_name
                FROM approval_requests ar
                JOIN approval_workflows aw ON ar.workflow_id = aw.id
                LEFT JOIN company_users cu ON ar.requested_by = cu.id
                {where}
                ORDER BY ar.created_at DESC
                LIMIT :limit OFFSET :offset
            """), params).fetchall()
    
            items = []
            for r in rows:
                item = dict(r._mapping)
                for k in ["created_at", "updated_at", "completed_at"]:
                    if k in item and item[k]:
                        item[k] = str(item[k])
                items.append(item)
    
            return {"items": items, "total": total, "page": page}
        except Exception:
            logger.error("Error listing approval requests")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/requests/{request_id}", dependencies=[Depends(require_permission("approvals.view"))], response_model=Dict[str, Any])
def get_approval_request(request_id: int, current_user=Depends(get_current_user)):
    """تفاصيل طلب اعتماد مع سجل الإجراءات"""
    with transactional(current_user.company_id) as db:
        try:
            request = db.execute(text("""
                SELECT ar.*, aw.name as workflow_name, aw.steps as workflow_steps,
                       cu.username as requested_by_name
                FROM approval_requests ar
                JOIN approval_workflows aw ON ar.workflow_id = aw.id
                LEFT JOIN company_users cu ON ar.requested_by = cu.id
                WHERE ar.id = :id
            """), {"id": request_id}).fetchone()
    
            if not request:
                raise HTTPException(**http_error(404, "approval_request_not_found"))
    
            # Get action history
            actions = db.execute(text("""
                SELECT aa.*, cu.username as actioned_by_name
                FROM approval_actions aa
                LEFT JOIN company_users cu ON aa.actioned_by = cu.id
                WHERE aa.request_id = :rid
                ORDER BY aa.actioned_at ASC
            """), {"rid": request_id}).fetchall()
    
            result = dict(request._mapping)
            for k in ["created_at", "updated_at", "completed_at"]:
                if k in result and result[k]:
                    result[k] = str(result[k])
            result["actions"] = [dict(a._mapping) for a in actions]
            for action in result["actions"]:
                if action.get("actioned_at"):
                    action["actioned_at"] = str(action["actioned_at"])
    
            return result
        except HTTPException:
            raise
        except Exception:
            logger.error("Error getting approval request")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/requests/{request_id}/action", dependencies=[Depends(require_permission("approvals.approve"))], response_model=Dict[str, Any])
def take_approval_action(request_id: int, data: ApprovalActionSchema, http_request: Request, current_user=Depends(get_current_user)):
    """
    اتخاذ إجراء على طلب اعتماد (اعتماد / رفض / إرجاع)
    """
    idempotency_key = require_idempotency_key(http_request, operation="approval action")
    with transactional(current_user.company_id) as db:
        try:
            import json

            replay = db.execute(text("""
                SELECT aa.request_id, aa.step, aa.action, aa.actioned_by,
                       ar.status, ar.current_step, ar.approvals_collected
                FROM approval_actions aa
                JOIN approval_requests ar ON ar.id = aa.request_id
                WHERE aa.idempotency_key = :idempotency_key
                LIMIT 1
            """), {"idempotency_key": idempotency_key}).fetchone()
            if replay:
                if replay.request_id != request_id or replay.action != data.action or replay.actioned_by != current_user.id:
                    raise HTTPException(**http_error(409, "duplicate_idempotency_key", http_request))
                return {
                    "message": i18n_message("approval_action_success", http_request, action=data.action),
                    "idempotent": True,
                    "request_id": request_id,
                    "step": replay.current_step,
                    "status": replay.status,
                    "approvals_collected": replay.approvals_collected or 0,
                }

            approval_request = db.execute(text("SELECT * FROM approval_requests WHERE id = :id FOR UPDATE"), {"id": request_id}).fetchone()
            if not approval_request:
                raise HTTPException(**http_error(404, "approval_request_not_found", http_request))
            if approval_request.status != 'pending':
                raise HTTPException(**http_error(400, "approval_action_invalid_status", http_request, status=approval_request.status))

            if data.action not in ('approve', 'reject', 'return'):
                raise HTTPException(**http_error(400, "approval_action_invalid", http_request))
    
            workflow = db.execute(text("SELECT * FROM approval_workflows WHERE id = :id"), {"id": approval_request.workflow_id}).fetchone()
            steps = workflow.steps if isinstance(workflow.steps, list) else json.loads(workflow.steps or "[]")
            total_steps = len(steps)
            try:
                current_step_info = steps[approval_request.current_step - 1]
            except (IndexError, TypeError):
                raise HTTPException(**http_error(400, "workflow_misconfigured_no_steps", http_request))

            if not _user_can_approve_step(current_user, current_step_info):
                raise HTTPException(**http_error(403, "permission_denied", http_request))

            # Quorum-aware duplicate guard: block the same user from acting twice
            # on the same step, but allow multiple distinct approvers when
            # ``quorum_required > 1``.
            already_by_user = db.execute(text(
                "SELECT action, idempotency_key FROM approval_actions "
                "WHERE request_id = :rid AND step = :step AND actioned_by = :uid"
            ), {"rid": request_id, "step": approval_request.current_step, "uid": current_user.id}).fetchone()
            if already_by_user:
                raise HTTPException(**http_error(409, "approval_already_actioned", http_request))
    
            # Record the action
            db.execute(text("""
                INSERT INTO approval_actions (request_id, step, action, actioned_by, notes, idempotency_key)
                VALUES (:rid, :step, :action, :uid, :notes, :idempotency_key)
            """), {
                "rid": request_id,
                "step": approval_request.current_step,
                "action": data.action,
                "uid": current_user.id,
                "notes": data.notes,
                "idempotency_key": idempotency_key
            })
    
            # Quorum: how many approvals required for the current step, and how many collected.
            quorum_required = getattr(approval_request, "quorum_required", None) or 1
            try:
                step_quorum = int(steps[approval_request.current_step - 1].get("quorum", quorum_required))
            except Exception:
                step_quorum = quorum_required
            approvals_collected = db.execute(text(
                "SELECT COUNT(*) FROM approval_actions "
                "WHERE request_id = :rid AND step = :step AND action = 'approve'"
            ), {"rid": request_id, "step": approval_request.current_step}).scalar() or 0
            # persist running tally
            db.execute(text(
                "UPDATE approval_requests SET approvals_collected = :c WHERE id = :id"
            ), {"c": approvals_collected, "id": request_id})

            final_approved = False
            response_payload = {
                "message": i18n_message("approval_action_success", http_request, action=data.action),
                "idempotent": False,
            }
    
            if data.action == 'approve':
                if approvals_collected < step_quorum:
                    response_payload = {
                        "ok": True,
                        "step": approval_request.current_step,
                        "approvals_collected": approvals_collected,
                        "quorum_required": step_quorum,
                        "status": "awaiting_quorum",
                        "idempotent": False,
                    }
                elif approval_request.current_step >= total_steps:
                    # Final approval - mark as approved
                    db.execute(text("""
                        UPDATE approval_requests
                        SET status = 'approved', completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                    """), {"id": request_id})
                    final_approved = True
    
                    # Notify requester of final approval
                    _create_notification(db, approval_request.requested_by,
                                         "✅ تم اعتماد طلبك",
                                         f"تم اعتماد الطلب رقم {request_id} نهائياً",
                                         f"/approvals/{request_id}")
                else:
                    # Move to next step
                    next_step = approval_request.current_step + 1
                    db.execute(text("""
                        UPDATE approval_requests
                        SET current_step = :next_step, updated_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                    """), {"id": request_id, "next_step": next_step})
    
                    # Notify next approver
                    if next_step <= len(steps):
                        next_step_info = steps[next_step - 1]
                        step_label = next_step_info.get("label", f"الخطوة {next_step}")
    
                        approvers = _find_approvers_for_step(db, next_step_info)
    
                        for approver in approvers:
                            _create_notification(db, approver.id,
                                                 f"طلب اعتماد بحاجة لمراجعتك - {step_label}",
                                                 f"الطلب رقم {request_id} بانتظار اعتمادك",
                                                 f"/approvals/{request_id}")
    
            elif data.action == 'reject':
                db.execute(text("""
                    UPDATE approval_requests
                    SET status = 'rejected', completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """), {"id": request_id})
    
                # Notify requester of rejection
                _create_notification(db, approval_request.requested_by,
                                     "❌ تم رفض طلبك",
                                     f"تم رفض الطلب رقم {request_id}: {data.notes or ''}",
                                     f"/approvals/{request_id}")
    
            elif data.action == 'return':
                # Return to previous step or to requester
                prev_step = max(1, approval_request.current_step - 1)
                db.execute(text("""
                    UPDATE approval_requests
                    SET current_step = :prev_step, status = 'returned', updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """), {"id": request_id, "prev_step": prev_step})
    
                _create_notification(db, approval_request.requested_by,
                                     "🔄 تم إرجاع طلبك للمراجعة",
                                     f"الطلب رقم {request_id}: {data.notes or ''}",
                                     f"/approvals/{request_id}")
    
            # ── Update source document status (callback) ──
            try:
                new_status = None
                if final_approved:
                    new_status = 'approved'
                elif data.action == 'reject':
                    new_status = 'rejected'
    
                if new_status and approval_request.document_type and approval_request.document_id:
                    doc_table_map = {
                        'purchase_order': 'purchase_orders',
                        'expense': 'expenses',
                        'leave_request': 'leave_requests',
                        'payment_voucher': 'payment_vouchers',
                        'sales_order': 'sales_orders',
                        'transfer': 'inventory_transfers',
                        'production_order': 'production_orders',
                    }
                    table_name = doc_table_map.get(approval_request.document_type)
                    if table_name:
                        # Verify table exists before updating
                        table_exists = db.execute(text(
                            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"
                        ), {"t": table_name}).scalar()
                        if table_exists:
                            db.execute(text(f"""
                                UPDATE {table_name}
                                SET status = :status, updated_at = CURRENT_TIMESTAMP
                                WHERE id = :doc_id
                            """), {"status": new_status, "doc_id": approval_request.document_id})
            except Exception:
                logger.warning(
                    "Approval callback failed for document_type=%s document_id=%s",
                    approval_request.document_type,
                    approval_request.document_id,
                )
    
    
            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action=data.action, resource_type="approval_requests",
                resource_id=str(request_id),
                details={
                    "action": data.action,
                    "step": approval_request.current_step,
                    "notes": data.notes,
                },
                request=http_request,
                critical=True,
            )
    
            return response_payload
        except HTTPException:
            raise
        except Exception:
            logger.error("Error taking approval action")
            raise HTTPException(**http_error(500, "internal_error"))


# ===================== Stats / Summary =====================

@router.get("/stats", dependencies=[Depends(require_permission("approvals.view"))], response_model=Dict[str, Any])
def approval_stats(current_user=Depends(get_current_user)):
    """إحصائيات الاعتمادات"""
    with transactional(current_user.company_id) as db:
        try:
            stats = db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'pending') as pending_count,
                    COUNT(*) FILTER (WHERE status = 'approved') as approved_count,
                    COUNT(*) FILTER (WHERE status = 'rejected') as rejected_count,
                    COUNT(*) FILTER (WHERE status = 'returned') as returned_count,
                    COUNT(*) as total_count
                FROM approval_requests
            """)).fetchone()
    
            return {
                "pending": stats.pending_count or 0,
                "approved": stats.approved_count or 0,
                "rejected": stats.rejected_count or 0,
                "returned": stats.returned_count or 0,
                "total": stats.total_count or 0
            }
        except Exception:
            logger.error("Error getting approval stats")
            raise HTTPException(**http_error(500, "internal_error"))


# ===================== Document Type Config =====================

@router.get("/document-types", dependencies=[Depends(require_permission("approvals.view"))], response_model=List[Dict[str, Any]])
def list_document_types(current_user=Depends(get_current_user)):
    """أنواع المستندات المتاحة لسلاسل الاعتماد"""
    return [
        {"value": "purchase_order", "label": "أمر شراء", "label_en": "Purchase Order"},
        {"value": "expense", "label": "مصروف", "label_en": "Expense"},
        {"value": "leave_request", "label": "طلب إجازة", "label_en": "Leave Request"},
        {"value": "payment_voucher", "label": "سند صرف", "label_en": "Payment Voucher"},
        {"value": "sales_order", "label": "أمر بيع", "label_en": "Sales Order"},
        {"value": "transfer", "label": "تحويل مالي", "label_en": "Transfer"},
        {"value": "production_order", "label": "أمر إنتاج", "label_en": "Production Order"},
    ]

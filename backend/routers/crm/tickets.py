"""crm sub-router — split from monolithic crm.py (T6.3).

Mounted under the parent router via crm/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import logging
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, require_module, validate_branch_access
from utils.accounting import generate_sequential_number
from utils.audit import log_activity
from utils.sql_builder import validate_update_keys
from services.notification_service import notification_service
from schemas.campaign import CampaignCreate, TrackingWebhookPayload

logger = logging.getLogger(__name__)

router = APIRouter()

from .core import CommentCreate, TicketCreate, TicketUpdate

@router.get("/tickets", dependencies=[Depends(require_permission(["sales.view", "projects.view"]))], response_model=List[Dict[str, Any]])
def list_tickets(
    status_filter: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[int] = None,
    branch_id: Optional[int] = None,
    current_user=Depends(get_current_user)
):
    """List Tickets."""
    # CRM-F1: enforce branch scope on list
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT t.*, p.name as customer_name, cu.username as assigned_name
            FROM support_tickets t
            LEFT JOIN parties p ON t.customer_id = p.id
            LEFT JOIN company_users cu ON t.assigned_to = cu.id
            WHERE 1=1
        """
        params = {}
        if branch_id:
            query += " AND t.branch_id = :branch_id"
            params["branch_id"] = branch_id
        else:
            allowed = getattr(current_user, "allowed_branches", None) or (
                current_user.get("allowed_branches") if isinstance(current_user, dict) else None
            )
            perms = getattr(current_user, "permissions", None) or (
                current_user.get("permissions") if isinstance(current_user, dict) else []
            ) or []
            if allowed and "*" not in perms:
                query += " AND t.branch_id = ANY(:allowed_branches)"
                params["allowed_branches"] = list(allowed)
        if status_filter:
            query += " AND t.status = :status"
            params["status"] = status_filter
        if priority:
            query += " AND t.priority = :priority"
            params["priority"] = priority
        if assigned_to:
            query += " AND t.assigned_to = :assigned"
            params["assigned"] = assigned_to
        
        query += " ORDER BY CASE t.priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, t.created_at DESC"
        rows = db.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.get("/tickets/stats", dependencies=[Depends(require_permission(["sales.view", "projects.view"]))], response_model=Dict[str, Any])
def get_ticket_stats(current_user=Depends(get_current_user)):
    """Get Ticket Stats."""
    db = get_db_connection(current_user.company_id)
    try:
        stats = db.execute(text("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'open') as open_count,
                COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress_count,
                COUNT(*) FILTER (WHERE status = 'resolved') as resolved_count,
                COUNT(*) FILTER (WHERE status = 'closed') as closed_count,
                COUNT(*) FILTER (WHERE priority = 'critical' AND status NOT IN ('resolved', 'closed')) as critical_open,
                COALESCE(AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600) 
                    FILTER (WHERE resolved_at IS NOT NULL), 0) as avg_resolution_hours
            FROM support_tickets
        """)).fetchone()
        return dict(stats._mapping) if stats else {}
    finally:
        db.close()


@router.get("/tickets/{ticket_id}", dependencies=[Depends(require_permission(["sales.view", "projects.view"]))], response_model=Dict[str, Any])
def get_ticket(ticket_id: int, current_user=Depends(get_current_user)):
    """Get Ticket."""
    db = get_db_connection(current_user.company_id)
    try:
        ticket = db.execute(text("""
            SELECT t.*, p.name as customer_name, cu.username as assigned_name
            FROM support_tickets t
            LEFT JOIN parties p ON t.customer_id = p.id
            LEFT JOIN company_users cu ON t.assigned_to = cu.id
            WHERE t.id = :id
        """), {"id": ticket_id}).fetchone()
        if not ticket:
            raise HTTPException(404, "التذكرة غير موجودة")
        
        comments = db.execute(text("""
            SELECT tc.*, cu.username as author_name
            FROM ticket_comments tc
            LEFT JOIN company_users cu ON tc.created_by = cu.id
            WHERE tc.ticket_id = :id ORDER BY tc.created_at ASC
        """), {"id": ticket_id}).fetchall()
        
        result = dict(ticket._mapping)
        result["comments"] = [dict(c._mapping) for c in comments]
        
        # SLA check (FR-007)
        if ticket.status not in ('resolved', 'closed'):
            sla_hours = ticket.sla_hours
            if not sla_hours:
                result["sla_status"] = "sla_not_configured"
            else:
                now = datetime.now(timezone.utc)
                hours_open = (now - ticket.created_at).total_seconds() / 3600
                result["sla_breached"] = hours_open > sla_hours
                result["hours_open"] = round(hours_open, 1)
                result["sla_status"] = "breached" if hours_open > sla_hours else "within_sla"
        
        return result
    finally:
        db.close()


@router.post("/tickets", status_code=201,
             dependencies=[Depends(require_permission(["sales.create", "projects.create"]))], response_model=Dict[str, Any])
def create_ticket(data: TicketCreate, request: Request, current_user=Depends(get_current_user)):
    """Create Ticket."""
    db = get_db_connection(current_user.company_id)
    try:
        ticket_num = generate_sequential_number(db, f"TKT-{datetime.now().year}", "support_tickets", "ticket_number")
        
        tid = db.execute(text("""
            INSERT INTO support_tickets (
                ticket_number, subject, description, customer_id,
                contact_name, contact_email, contact_phone,
                priority, category, assigned_to, branch_id, sla_hours, created_by
            ) VALUES (
                :num, :subject, :desc, :cust,
                :cname, :cemail, :cphone,
                :priority, :category, :assigned, :branch, :sla, :user
            ) RETURNING id
        """), {
            "num": ticket_num, "subject": data.subject, "desc": data.description,
            "cust": data.customer_id, "cname": data.contact_name,
            "cemail": data.contact_email, "cphone": data.contact_phone,
            "priority": data.priority, "category": data.category,
            "assigned": data.assigned_to, "branch": data.branch_id,
            "sla": data.sla_hours, "user": current_user.id
        }).scalar()
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_create_ticket", resource_type="ticket", resource_id=str(tid), details={"ticket_number": ticket_num, "subject": data.subject, "priority": data.priority}, request=request)
        
        return {"id": tid, "ticket_number": ticket_num, "message": "تم إنشاء التذكرة"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating ticket: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/tickets/{ticket_id}", dependencies=[Depends(require_permission(["sales.create", "projects.edit"]))], response_model=Dict[str, Any])
async def update_ticket(ticket_id: int, data: TicketUpdate, request: Request, current_user=Depends(get_current_user)):
    """Update Ticket."""
    db = get_db_connection(current_user.company_id)
    try:
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        if not updates:
            raise HTTPException(**http_error(400, "no_data_to_update"))
        
        # Auto-set timestamps
        if updates.get("status") == "resolved":
            updates["resolved_at"] = datetime.now()
        elif updates.get("status") == "closed":
            updates["closed_at"] = datetime.now()
        
        validate_update_keys(updates.keys())  # T2.2 defense-in-depth
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = ticket_id
        db.execute(text(f"UPDATE support_tickets SET {set_clause}, updated_at = NOW() WHERE id = :id"), updates)
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_update_ticket", resource_type="ticket", resource_id=str(ticket_id), details={"fields_updated": list(updates.keys())}, request=request)

        # Dispatch notification when ticket is assigned to a user
        assigned_to = updates.get("assigned_to")
        if assigned_to:
            try:
                await notification_service.dispatch(
                    db=get_db_connection(current_user.company_id),
                    company_id=current_user.company_id,
                    recipient_id=assigned_to,
                    event_type="crm.ticket_assigned",
                    title="تم تعيين تذكرة دعم إليك",
                    body=f"تم تعيين التذكرة #{ticket_id} إليك",
                    feature_source="crm",
                    reference_type="ticket",
                    reference_id=ticket_id,
                    link=f"/crm/tickets/{ticket_id}",
                )
            except Exception as notif_err:
                logger.warning("Failed to dispatch ticket assignment notification: %s", notif_err)

        return {"message": "تم التحديث"}
    finally:
        db.close()


@router.post("/tickets/{ticket_id}/comments", status_code=201,
             dependencies=[Depends(require_permission(["sales.create", "projects.edit"]))], response_model=Dict[str, Any])
def add_comment(ticket_id: int, data: CommentCreate, request: Request, current_user=Depends(get_current_user)):
    """Add Comment."""
    db = get_db_connection(current_user.company_id)
    try:
        cid = db.execute(text("""
            INSERT INTO ticket_comments (ticket_id, comment, is_internal, attachment_url, created_by)
            VALUES (:tid, :comment, :internal, :attach, :user) RETURNING id
        """), {
            "tid": ticket_id, "comment": data.comment,
            "internal": data.is_internal, "attach": data.attachment_url,
            "user": current_user.id
        }).scalar()
        
        db.execute(text("UPDATE support_tickets SET updated_at = NOW() WHERE id = :id"), {"id": ticket_id})
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_add_ticket_comment", resource_type="ticket_comment", resource_id=str(cid), details={"ticket_id": ticket_id, "is_internal": data.is_internal}, request=request)
        return {"id": cid}
    finally:
        db.close()


# ======================== CRM-001: Convert Opportunity to Quotation ========================


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

from .core import ActivityCreate, OPPORTUNITY_ALLOWED_FIELDS, OPPORTUNITY_STAGES, OpportunityCreate, OpportunityUpdate

@router.get("/opportunities", dependencies=[Depends(require_permission(["sales.view", "projects.view"]))], response_model=List[Dict[str, Any]])
def list_opportunities(
    stage: Optional[str] = None,
    assigned_to: Optional[int] = None,
    branch_id: Optional[int] = None,
    current_user=Depends(get_current_user)
):
    # CRM-F1: enforce branch scope on list
    branch_id = validate_branch_access(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT o.*, p.name as customer_name,
                   cu.username as assigned_name
            FROM sales_opportunities o
            LEFT JOIN parties p ON o.customer_id = p.id
            LEFT JOIN company_users cu ON o.assigned_to = cu.id
            WHERE 1=1
        """
        params = {}
        if branch_id:
            query += " AND o.branch_id = :branch_id"
            params["branch_id"] = branch_id
        else:
            allowed = getattr(current_user, "allowed_branches", None) or (
                current_user.get("allowed_branches") if isinstance(current_user, dict) else None
            )
            perms = getattr(current_user, "permissions", None) or (
                current_user.get("permissions") if isinstance(current_user, dict) else []
            ) or []
            if allowed and "*" not in perms:
                query += " AND o.branch_id = ANY(:allowed_branches)"
                params["allowed_branches"] = list(allowed)
        if stage:
            query += " AND o.stage = :stage"
            params["stage"] = stage
        if assigned_to:
            query += " AND o.assigned_to = :assigned"
            params["assigned"] = assigned_to
        
        query += " ORDER BY o.updated_at DESC"
        rows = db.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.get("/opportunities/pipeline", dependencies=[Depends(require_permission(["sales.view", "projects.view"]))], response_model=Dict[str, Any])
def get_pipeline_summary(current_user=Depends(get_current_user)):
    """Get opportunity pipeline summary by stage."""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT stage, COUNT(*) as count, 
                   COALESCE(SUM(expected_value), 0) as total_value,
                   COALESCE(AVG(probability), 0) as avg_probability
            FROM sales_opportunities
            WHERE stage NOT IN ('won', 'lost')
            GROUP BY stage
            ORDER BY 
                CASE stage 
                    WHEN 'lead' THEN 1 
                    WHEN 'qualified' THEN 2 
                    WHEN 'proposal' THEN 3 
                    WHEN 'negotiation' THEN 4 
                END
        """)).fetchall()
        
        # Also get won/lost stats
        stats = db.execute(text("""
            SELECT 
                COUNT(*) FILTER (WHERE stage = 'won') as won_count,
                COALESCE(SUM(expected_value) FILTER (WHERE stage = 'won'), 0) as won_value,
                COUNT(*) FILTER (WHERE stage = 'lost') as lost_count,
                COUNT(*) as total
            FROM sales_opportunities
        """)).fetchone()
        
        return {
            "pipeline": [dict(r._mapping) for r in rows],
            "stats": dict(stats._mapping) if stats else {},
            "stages": OPPORTUNITY_STAGES
        }
    finally:
        db.close()


@router.get("/opportunities/{opp_id}", dependencies=[Depends(require_permission(["sales.view", "projects.view"]))], response_model=Dict[str, Any])
def get_opportunity(opp_id: int, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        opp = db.execute(text("""
            SELECT o.*, p.name as customer_name, cu.username as assigned_name
            FROM sales_opportunities o
            LEFT JOIN parties p ON o.customer_id = p.id
            LEFT JOIN company_users cu ON o.assigned_to = cu.id
            WHERE o.id = :id
        """), {"id": opp_id}).fetchone()
        if not opp:
            raise HTTPException(**http_error(404, "opportunity_not_found"))
        
        activities = db.execute(text("""
            SELECT * FROM opportunity_activities WHERE opportunity_id = :id ORDER BY created_at DESC
        """), {"id": opp_id}).fetchall()
        
        result = dict(opp._mapping)
        result["activities"] = [dict(a._mapping) for a in activities]
        return result
    finally:
        db.close()


@router.post("/opportunities", status_code=201, dependencies=[Depends(require_permission(["sales.create", "projects.create"]))], response_model=Dict[str, Any])
def create_opportunity(data: OpportunityCreate, request: Request, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        opp_id = db.execute(text("""
            INSERT INTO sales_opportunities (
                title, customer_id, contact_name, contact_email, contact_phone,
                stage, probability, expected_value, expected_close_date,
                currency, source, assigned_to, branch_id, notes, created_by
            ) VALUES (
                :title, :cust, :cname, :cemail, :cphone,
                :stage, :prob, :val, :close,
                :curr, :src, :assigned, :branch, :notes, :user
            ) RETURNING id
        """), {
            "title": data.title, "cust": data.customer_id,
            "cname": data.contact_name, "cemail": data.contact_email,
            "cphone": data.contact_phone, "stage": data.stage,
            "prob": data.probability, "val": data.expected_value,
            "close": data.expected_close_date, "curr": data.currency,
            "src": data.source, "assigned": data.assigned_to,
            "branch": data.branch_id, "notes": data.notes,
            "user": current_user.id
        }).scalar()
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_create_opportunity", resource_type="opportunity", resource_id=str(opp_id), details={"title": data.title, "stage": data.stage}, request=request)
        return {"id": opp_id, "message": "تم إنشاء الفرصة البيعية"}
    finally:
        db.close()


@router.put("/opportunities/{opp_id}", dependencies=[Depends(require_permission(["sales.create", "projects.edit"]))], response_model=Dict[str, Any])
async def update_opportunity(opp_id: int, data: OpportunityUpdate, request: Request, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        updates = {k: v for k, v in data.model_dump().items()
                   if v is not None and k in OPPORTUNITY_ALLOWED_FIELDS}
        if not updates:
            raise HTTPException(**http_error(400, "no_data_to_update"))
        
        # Auto-set probability based on stage
        if "stage" in updates and updates["stage"] in OPPORTUNITY_STAGES:
            if "probability" not in updates:
                updates["probability"] = OPPORTUNITY_STAGES[updates["stage"]]
        
        validate_update_keys(updates.keys())  # T2.2 defense-in-depth
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = opp_id
        db.execute(text(f"UPDATE sales_opportunities SET {set_clause}, updated_at = NOW() WHERE id = :id"), updates)
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_update_opportunity", resource_type="opportunity", resource_id=str(opp_id), details={"fields_updated": list(updates.keys())}, request=request)

        # Dispatch notification when opportunity stage changes to won or lost
        stage = updates.get("stage")
        if stage in ("won", "lost"):
            try:
                assigned = db.execute(
                    text("SELECT assigned_to FROM sales_opportunities WHERE id = :id"),
                    {"id": opp_id}
                ).scalar()
                if assigned:
                    await notification_service.dispatch(
                        db=get_db_connection(current_user.company_id),
                        company_id=current_user.company_id,
                        recipient_id=assigned,
                        event_type=f"crm.opportunity_{stage}",
                        title=f"الفرصة البيعية {'مكتسبة' if stage == 'won' else 'خاسرة'}",
                        body=f"تم تحديث الفرصة #{opp_id} إلى مرحلة {stage}",
                        feature_source="crm",
                        reference_type="opportunity",
                        reference_id=opp_id,
                        link=f"/crm/opportunities/{opp_id}",
                    )
            except Exception as notif_err:
                logger.warning("Failed to dispatch opportunity stage notification: %s", notif_err)

        return {"message": "تم التحديث"}
    finally:
        db.close()


@router.delete("/opportunities/{opp_id}", dependencies=[Depends(require_permission(["sales.delete", "projects.delete"]))], response_model=Dict[str, Any])
def delete_opportunity(opp_id: int, request: Request, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("DELETE FROM sales_opportunities WHERE id = :id"), {"id": opp_id})
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_delete_opportunity", resource_type="opportunity", resource_id=str(opp_id), details={}, request=request)
        return {"message": "تم حذف الفرصة"}
    finally:
        db.close()


@router.post("/opportunities/{opp_id}/activities", status_code=201,
             dependencies=[Depends(require_permission(["sales.create", "projects.edit"]))], response_model=Dict[str, Any])
def add_activity(opp_id: int, data: ActivityCreate, request: Request, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        aid = db.execute(text("""
            INSERT INTO opportunity_activities (opportunity_id, activity_type, title, description, due_date, created_by)
            VALUES (:opp, :type, :title, :desc, :due, :user) RETURNING id
        """), {
            "opp": opp_id, "type": data.activity_type,
            "title": data.title, "desc": data.description,
            "due": data.due_date, "user": current_user.id
        }).scalar()
        
        # Update opportunity's updated_at
        db.execute(text("UPDATE sales_opportunities SET updated_at = NOW() WHERE id = :id"), {"id": opp_id})
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_add_activity", resource_type="activity", resource_id=str(aid), details={"opportunity_id": opp_id, "activity_type": data.activity_type, "title": data.title}, request=request)
        return {"id": aid}
    finally:
        db.close()


# ======================== CRM-004: Support Tickets ========================

@router.post("/opportunities/{opp_id}/convert-quotation", status_code=201,
             dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def convert_to_quotation(opp_id: int, request: Request, current_user=Depends(get_current_user)):
    """تحويل فرصة بيعية إلى عرض سعر"""
    db = get_db_connection(current_user.company_id)
    try:
        opp = db.execute(text("SELECT * FROM sales_opportunities WHERE id = :id"), {"id": opp_id}).fetchone()
        if not opp:
            raise HTTPException(**http_error(404, "opportunity_not_found"))
        opp = opp._mapping

        # T003: Block duplicate conversion — check if quotation already exists
        if opp.get("won_quotation_id"):
            raise HTTPException(
                status_code=409,
                detail={"error": "quotation_already_exists", "quotation_id": opp["won_quotation_id"]}
            )

        # T008: Use http_error helper (Constitution IV)
        if not opp.get("customer_id"):
            raise HTTPException(**http_error(400, "opportunity_no_customer"))

        # T004: Fix generate_sequential_number column name: "quotation_number" → "sq_number"
        quot_num = generate_sequential_number(db, f"QT-{datetime.now().year}", "sales_quotations", "sq_number")

        # T005: Fix INSERT column names: quotation_number → sq_number, valid_until → expiry_date
        quot_id = db.execute(text("""
            INSERT INTO sales_quotations (
                sq_number, customer_id, quotation_date, expiry_date,
                subtotal, tax_amount, discount, total, status, notes, created_by, branch_id
            ) VALUES (
                :num, :cust, CURRENT_DATE, CURRENT_DATE + INTERVAL '30 days',
                :amt, 0, 0, :amt, 'draft',
                :notes, :uid, :branch
            ) RETURNING id
        """), {
            "num": quot_num,
            "cust": opp["customer_id"],
            "amt": opp.get("expected_value") or 0,
            "notes": f"تم التحويل من فرصة: {opp['title']}",
            "uid": current_user.id,
            "branch": opp.get("branch_id")
        }).scalar()

        # T006: Fix line INSERT column name: quotation_id → sq_id
        if opp.get("expected_value") and opp["expected_value"] > 0:
            db.execute(text("""
                INSERT INTO sales_quotation_lines (sq_id, description, quantity, unit_price, tax_rate, discount, total)
                VALUES (:qid, :desc, 1, :price, 0, 0, :price)
            """), {
                "qid": quot_id,
                "desc": opp["title"],
                "price": opp["expected_value"]
            })

        # T007: Write won_quotation_id back to opportunity + update stage to 'proposal'
        db.execute(text("""
            UPDATE sales_opportunities
            SET stage = 'proposal', won_quotation_id = :qid, updated_at = NOW()
            WHERE id = :id
        """), {"qid": quot_id, "id": opp_id})
        db.commit()

        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_convert_opportunity_to_quotation", resource_type="opportunity", resource_id=str(opp_id), details={"quotation_id": quot_id, "quotation_number": quot_num}, request=request)
        return {"quotation_id": quot_id, "quotation_number": quot_num, "message": "تم تحويل الفرصة إلى عرض سعر"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error converting opportunity to quotation: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ======================== CRM-003: Marketing Campaigns ========================

from schemas.campaign import CampaignCreate, TrackingWebhookPayload


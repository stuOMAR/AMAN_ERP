"""crm sub-router — split from monolithic crm.py (T6.3).

Mounted under the parent router via crm/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
from decimal import Decimal, ROUND_HALF_UP
import logging
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter, require_permission, require_module, validate_branch_access
from utils.accounting import generate_sequential_number
from utils.audit import log_activity
from utils.sql_builder import validate_update_keys
from services.notification_service import notification_service
from services.tax_engine import resolve_line_tax
from schemas.campaign import CampaignCreate, TrackingWebhookPayload

logger = logging.getLogger(__name__)

router = APIRouter()

from .core import ActivityCreate, ActivityUpdate, OPPORTUNITY_ALLOWED_FIELDS, OPPORTUNITY_STAGES, OpportunityCreate, OpportunityUpdate

@router.get("/opportunities", dependencies=[Depends(require_permission(["sales.view", "projects.view"]))], response_model=List[Dict[str, Any]])
def list_opportunities(
    stage: Optional[str] = None,
    assigned_to: Optional[int] = None,
    branch_id: Optional[int] = None,
    current_user=Depends(get_current_user)
):
    """List Opportunities."""
    db = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT o.*, p.name as customer_name,
                   cu.username as assigned_name
            FROM sales_opportunities o
            LEFT JOIN parties p ON o.customer_id = p.id
            LEFT JOIN company_users cu ON o.assigned_to = cu.id
            WHERE COALESCE(o.is_deleted, FALSE) = FALSE
        """
        params = {}
        query += " " + branch_scope_filter(current_user, branch_id, "o.branch_id", params)
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
            WHERE stage NOT IN ('won', 'lost') AND COALESCE(is_deleted, FALSE) = FALSE
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
            WHERE COALESCE(is_deleted, FALSE) = FALSE
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
    """Get Opportunity."""
    db = get_db_connection(current_user.company_id)
    try:
        opp = db.execute(text("""
            SELECT o.*, p.name as customer_name, cu.username as assigned_name
            FROM sales_opportunities o
            LEFT JOIN parties p ON o.customer_id = p.id
            LEFT JOIN company_users cu ON o.assigned_to = cu.id
            WHERE o.id = :id AND COALESCE(o.is_deleted, FALSE) = FALSE
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
    """Create Opportunity."""
    db = get_db_connection(current_user.company_id)
    try:
        if data.customer_id and data.expected_value and data.expected_value > 0:
            credit = db.execute(text("""
                SELECT credit_limit, current_balance
                FROM parties
                WHERE id = :id AND is_customer = TRUE
            """), {"id": data.customer_id}).fetchone()
            if credit and credit.credit_limit and float(credit.credit_limit) > 0:
                projected = float(credit.current_balance or 0) + float(data.expected_value or 0)
                if projected > float(credit.credit_limit):
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "credit_limit_exceeded",
                            "credit_limit": float(credit.credit_limit),
                            "current_balance": float(credit.current_balance or 0),
                            "opportunity_value": float(data.expected_value or 0),
                        },
                    )

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
    """Update Opportunity."""
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
    """Soft-delete an opportunity (T10.1 P1 #38).

    Hard DELETE used to discard valuable historical data and break
    downstream analytics that JOIN on opportunity_id (activities,
    quotations, lead-scoring history). We now flip ``is_deleted`` and
    keep the row so:
      * pipeline analytics remain consistent over time;
      * already-converted quotations still resolve their source
        opportunity for traceability;
      * audit log retains a stable resource_id.
    """
    db = get_db_connection(current_user.company_id)
    try:
        existing = db.execute(
            text("SELECT id, is_deleted FROM sales_opportunities WHERE id = :id"),
            {"id": opp_id},
        ).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "opportunity_not_found"))
        if existing.is_deleted:
            return {"message": "تم حذف الفرصة مسبقاً"}
        db.execute(
            text(
                "UPDATE sales_opportunities "
                "SET is_deleted = TRUE, deleted_at = NOW(), updated_at = NOW() "
                "WHERE id = :id"
            ),
            {"id": opp_id},
        )
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_delete_opportunity", resource_type="opportunity", resource_id=str(opp_id), details={"soft_delete": True}, request=request)
        return {"message": "تم حذف الفرصة"}
    finally:
        db.close()


@router.post("/opportunities/{opp_id}/activities", status_code=201,
             dependencies=[Depends(require_permission(["sales.create", "projects.edit"]))], response_model=Dict[str, Any])
def add_activity(opp_id: int, data: ActivityCreate, request: Request, current_user=Depends(get_current_user)):
    """Add Activity."""
    db = get_db_connection(current_user.company_id)
    try:
        opp = db.execute(
            text("SELECT id, customer_id FROM sales_opportunities WHERE id = :id"),
            {"id": opp_id},
        ).fetchone()
        if not opp:
            raise HTTPException(**http_error(404, "opportunity_not_found"))
        if data.contact_id:
            contact = db.execute(
                text("SELECT id, customer_id FROM crm_contacts WHERE id = :id"),
                {"id": data.contact_id},
            ).fetchone()
            if not contact or (opp.customer_id and contact.customer_id != opp.customer_id):
                raise HTTPException(status_code=400, detail="contact_not_linked_to_opportunity_customer")

        # T10.2 #151: persist the new completion-tracking fields. ``completed``
        # is the existing column on opportunity_activities; ``is_completed``
        # in the API payload maps to it. ``completed_at`` is auto-set when
        # the caller marks the activity completed at creation time.
        completed_flag = bool(data.is_completed) if data.is_completed is not None else False
        aid = db.execute(text("""
            INSERT INTO opportunity_activities (
                opportunity_id, activity_type, title, contact_id, description, due_date,
                outcome, duration_minutes, completed, completed_at, created_by
            )
            VALUES (
                :opp, :type, :title, :contact_id, :desc, :due,
                :outcome, :dur, :completed,
                CASE WHEN :completed THEN NOW() ELSE NULL END,
                :user
            ) RETURNING id
        """), {
            "opp": opp_id, "type": data.activity_type,
            "title": data.title, "contact_id": data.contact_id, "desc": data.description,
            "due": data.due_date,
            "outcome": data.outcome,
            "dur": data.duration_minutes,
            "completed": completed_flag,
            "user": current_user.id
        }).scalar()
        
        # Update opportunity's updated_at
        db.execute(text("UPDATE sales_opportunities SET updated_at = NOW() WHERE id = :id"), {"id": opp_id})
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_add_activity", resource_type="activity", resource_id=str(aid), details={"opportunity_id": opp_id, "activity_type": data.activity_type, "title": data.title}, request=request)
        return {"id": aid}
    finally:
        db.close()


@router.patch("/opportunities/{opp_id}/activities/{aid}",
              dependencies=[Depends(require_permission(["sales.create", "projects.edit"]))],
              response_model=Dict[str, Any])
def update_activity(opp_id: int, aid: int, data: ActivityUpdate, request: Request,
                    current_user=Depends(get_current_user)):
    """T10.2 #150: partial update of an opportunity activity (typically
    used to mark it completed with outcome + duration). Whitelisted
    columns only; ``is_completed`` maps to the ``completed`` column and
    auto-populates ``completed_at`` when transitioning to TRUE.
    """
    db = get_db_connection(current_user.company_id)
    try:
        existing = db.execute(text(
            "SELECT id, completed FROM opportunity_activities "
            "WHERE id = :aid AND opportunity_id = :opp"
        ), {"aid": aid, "opp": opp_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Activity not found")

        sets = []
        params: Dict[str, Any] = {"aid": aid, "opp": opp_id}
        for field in ("activity_type", "title", "description", "due_date",
                      "outcome", "duration_minutes", "contact_id"):
            val = getattr(data, field)
            if val is not None:
                if field == "contact_id":
                    contact = db.execute(text("""
                        SELECT c.id
                        FROM crm_contacts c
                        JOIN sales_opportunities o ON o.id = :opp
                        WHERE c.id = :cid
                          AND (o.customer_id IS NULL OR c.customer_id = o.customer_id)
                    """), {"cid": val, "opp": opp_id}).fetchone()
                    if not contact:
                        raise HTTPException(status_code=400, detail="contact_not_linked_to_opportunity_customer")
                sets.append(f"{field} = :{field}")
                params[field] = val
        if data.is_completed is not None:
            sets.append("completed = :completed")
            params["completed"] = bool(data.is_completed)
            # Set completed_at on first transition to TRUE; clear on FALSE.
            if data.is_completed and not existing.completed:
                sets.append("completed_at = NOW()")
            elif data.is_completed is False:
                sets.append("completed_at = NULL")

        if not sets:
            return {"id": aid, "updated": False}

        db.execute(text(
            f"UPDATE opportunity_activities SET {', '.join(sets)} "
            f"WHERE id = :aid AND opportunity_id = :opp"
        ), params)
        db.execute(text("UPDATE sales_opportunities SET updated_at = NOW() WHERE id = :id"),
                   {"id": opp_id})
        db.commit()
        log_activity(
            db, user_id=current_user.id,
            username=getattr(current_user, "username", ""),
            action="crm_update_activity",
            resource_type="activity", resource_id=str(aid),
            details={"opportunity_id": opp_id, "fields": [k for k in params if k not in ("aid", "opp")]},
            request=request,
        )
        return {"id": aid, "updated": True}
    finally:
        db.close()


# ======================== CRM-004: Support Tickets ========================

class OppConvertLine(BaseModel):
    description: str
    quantity: float = 1
    unit_price: float = 0
    tax_rate: Optional[Decimal] = None
    discount: float = 0
    product_id: Optional[int] = None


class OppConvertBody(BaseModel):
    """Optional override body for opportunity → quotation conversion (T10.1 P1 #39).

    If ``lines`` is supplied, the quotation is created with those lines
    instead of a single fallback line containing the opportunity title.
    """
    lines: Optional[List[OppConvertLine]] = None
    notes: Optional[str] = None


@router.post("/opportunities/{opp_id}/convert-quotation", status_code=201,
             dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def convert_to_quotation(
    opp_id: int,
    request: Request,
    body: Optional[OppConvertBody] = None,
    current_user=Depends(get_current_user),
):
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

        # T10.1 P1 #39 — preserve opportunity detail when converting:
        # if explicit lines are supplied in the request body, use them;
        # otherwise fall back to a single line carrying expected_value.
        body_lines = (body.lines if body and body.lines else None)
        _D2 = Decimal('0.01')
        _branch_id = opp.get("branch_id")
        _customer_id = opp.get("customer_id")
        if body_lines:
            subtotal = Decimal('0')
            tax_total = Decimal('0')
            grand_total = Decimal('0')
            for ln in body_lines:
                line_sub = Decimal(str(ln.quantity)) * Decimal(str(ln.unit_price)) - Decimal(str(ln.discount or 0))
                if ln.product_id and _branch_id:
                    tax_info = resolve_line_tax(_branch_id, ln.product_id, db, customer_id=_customer_id)
                    tax_rate = tax_info["tax_rate"]
                else:
                    tax_rate = Decimal(str(ln.tax_rate or 0))
                line_tax = (line_sub * tax_rate / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
                subtotal += line_sub
                tax_total += line_tax
                grand_total += line_sub + line_tax
        else:
            subtotal = Decimal(str(opp.get("expected_value") or 0))
            tax_total = Decimal('0')
            grand_total = subtotal

        notes_val = (body.notes if body and body.notes else f"تم التحويل من فرصة: {opp['title']}")

        # T005: Fix INSERT column names: quotation_number → sq_number, valid_until → expiry_date
        quot_id = db.execute(text("""
            INSERT INTO sales_quotations (
                sq_number, customer_id, quotation_date, expiry_date,
                subtotal, tax_amount, discount, total, status, notes, created_by, branch_id
            ) VALUES (
                :num, :cust, CURRENT_DATE, CURRENT_DATE + INTERVAL '30 days',
                :sub, :tax, 0, :tot, 'draft',
                :notes, :uid, :branch
            ) RETURNING id
        """), {
            "num": quot_num,
            "cust": opp["customer_id"],
            "sub": float(subtotal),
            "tax": float(tax_total),
            "tot": float(grand_total),
            "notes": notes_val,
            "uid": current_user.id,
            "branch": opp.get("branch_id")
        }).scalar()

        # T006: Fix line INSERT column name: quotation_id → sq_id
        if body_lines:
            for ln in body_lines:
                line_sub = Decimal(str(ln.quantity)) * Decimal(str(ln.unit_price)) - Decimal(str(ln.discount or 0))
                if ln.product_id and _branch_id:
                    tax_info = resolve_line_tax(_branch_id, ln.product_id, db, customer_id=_customer_id)
                    tax_rate = tax_info["tax_rate"]
                    tax_rate_id = tax_info.get("tax_rate_id")
                else:
                    tax_rate = Decimal(str(ln.tax_rate or 0))
                    tax_rate_id = None
                line_tax = (line_sub * tax_rate / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
                db.execute(text("""
                    INSERT INTO sales_quotation_lines (sq_id, product_id, description, quantity, unit_price, tax_rate, tax_rate_id, discount, total)
                    VALUES (:qid, :pid, :desc, :qty, :price, :rate, :rate_id, :disc, :tot)
                """), {
                    "qid": quot_id,
                    "pid": ln.product_id,
                    "desc": ln.description,
                    "qty": ln.quantity,
                    "price": ln.unit_price,
                    "rate": float(tax_rate),
                    "rate_id": tax_rate_id,
                    "disc": ln.discount or 0,
                    "tot": float(line_sub + line_tax),
                })
        elif opp.get("expected_value") and opp["expected_value"] > 0:
            db.execute(text("""
                INSERT INTO sales_quotation_lines (sq_id, description, quantity, unit_price, tax_rate, discount, total)
                VALUES (:qid, :desc, 1, :price, 0, 0, :price)
            """), {
                "qid": quot_id,
                "desc": opp["title"],
                "price": opp["expected_value"]
            })

        # T007: Link quotation without regressing an already-advanced stage.
        db.execute(text("""
            UPDATE sales_opportunities
            SET stage = CASE
                    WHEN stage IN ('lead', 'qualified') THEN 'proposal'
                    ELSE stage
                END,
                won_quotation_id = :qid,
                updated_at = NOW()
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


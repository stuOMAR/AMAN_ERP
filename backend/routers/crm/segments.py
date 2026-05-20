"""crm sub-router — split from monolithic crm.py (T6.3).

Mounted under the parent router via crm/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
from decimal import Decimal
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

from .core import LeadScoringRuleCreate, LeadScoringRuleUpdate, SegmentCreate, SegmentUpdate

@router.get("/lead-scoring/rules", dependencies=[Depends(require_permission("sales.view"))], response_model=List[Dict[str, Any]])
def list_scoring_rules(current_user=Depends(get_current_user)):
    """قائمة قواعد تسجيل العملاء المحتملين"""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT * FROM crm_lead_scoring_rules ORDER BY score DESC
        """)).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.post("/lead-scoring/rules", status_code=201, dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def create_scoring_rule(data: LeadScoringRuleCreate, request: Request, current_user=Depends(get_current_user)):
    """إنشاء قاعدة تسجيل نقاط"""
    db = get_db_connection(current_user.company_id)
    try:
        rid = db.execute(text("""
            INSERT INTO crm_lead_scoring_rules (rule_name, field_name, operator, field_value, score, created_by)
            VALUES (:name, :field, :op, :val, :score, :uid) RETURNING id
        """), {
            "name": data.rule_name, "field": data.field_name,
            "op": data.operator, "val": data.field_value,
            "score": data.score, "uid": current_user.id
        }).scalar()
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_create_scoring_rule", resource_type="lead_scoring_rule", resource_id=str(rid), details={"rule_name": data.rule_name, "score": data.score}, request=request)
        return {"id": rid, "message": i18n_message("segment_rule_created", request)}
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating scoring rule: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/lead-scoring/rules/{rule_id}", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def update_scoring_rule(rule_id: int, data: LeadScoringRuleUpdate, request: Request, current_user=Depends(get_current_user)):
    """Update Scoring Rule."""
    db = get_db_connection(current_user.company_id)
    try:
        updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
        if not updates:
            raise HTTPException(**http_error(400, "no_data_to_update"))
        updates["id"] = rule_id
        validate_update_keys(k for k in updates if k != "id")  # T2.2 defense-in-depth
        set_clause = ", ".join(f"{k} = :{k}" for k in updates if k != "id")
        db.execute(text(f"UPDATE crm_lead_scoring_rules SET {set_clause} WHERE id = :id"), updates)
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_update_scoring_rule", resource_type="lead_scoring_rule", resource_id=str(rule_id), details={"fields_updated": list(updates.keys())}, request=request)
        return {"message": i18n_message("webhook_updated_success", request)}
    finally:
        db.close()


@router.delete("/lead-scoring/rules/{rule_id}", dependencies=[Depends(require_permission("sales.delete"))], response_model=Dict[str, Any])
def delete_scoring_rule(rule_id: int, request: Request, current_user=Depends(get_current_user)):
    """Delete Scoring Rule."""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("DELETE FROM crm_lead_scoring_rules WHERE id = :id"), {"id": rule_id})
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_delete_scoring_rule", resource_type="lead_scoring_rule", resource_id=str(rule_id), details={}, request=request)
        return {"message": i18n_message("webhook_deleted_success", request)}
    finally:
        db.close()


@router.post("/lead-scoring/calculate", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def calculate_lead_scores(request: Request, current_user=Depends(get_current_user)):
    """حساب نقاط جميع الفرص تلقائياً بناءً على القواعد"""
    db = get_db_connection(current_user.company_id)
    try:
        rules = db.execute(text(
            "SELECT * FROM crm_lead_scoring_rules WHERE is_active = TRUE"
        )).fetchall()
        opps = db.execute(text(
            "SELECT * FROM sales_opportunities WHERE stage NOT IN ('won','lost')"
        )).fetchall()

        scored = 0
        for opp in opps:
            opp_d = dict(opp._mapping)
            total = 0
            details = []
            for r in rules:
                r_d = dict(r._mapping)
                val = str(opp_d.get(r_d["field_name"], "") or "")
                match = False
                if r_d["operator"] == "equals":
                    match = val.lower() == (r_d["field_value"] or "").lower()
                elif r_d["operator"] == "contains":
                    match = (r_d["field_value"] or "").lower() in val.lower()
                elif r_d["operator"] == "greater_than":
                    try:
                        match = Decimal(str(val)) > Decimal(str(r_d["field_value"] or 0))
                    except (ValueError, TypeError, Exception):
                        pass
                elif r_d["operator"] == "less_than":
                    try:
                        match = Decimal(str(val)) < Decimal(str(r_d["field_value"] or 0))
                    except (ValueError, TypeError, Exception):
                        pass
                elif r_d["operator"] == "exists":
                    match = bool(val and val.strip())

                if match:
                    total += r_d["score"]
                    details.append({"rule": r_d["rule_name"], "score": r_d["score"]})

            grade = "A" if total >= 80 else "B" if total >= 60 else "C" if total >= 40 else "D"

            import json
            db.execute(text("""
                INSERT INTO crm_lead_scores (opportunity_id, total_score, grade, scoring_details, last_scored_at)
                VALUES (:oid, :score, :grade, :details, NOW())
                ON CONFLICT (opportunity_id) DO UPDATE SET
                    total_score = EXCLUDED.total_score,
                    grade = EXCLUDED.grade,
                    scoring_details = EXCLUDED.scoring_details,
                    last_scored_at = NOW()
            """), {
                "oid": opp_d["id"], "score": total,
                "grade": grade, "details": json.dumps(details)
            })
            scored += 1

        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_calculate_lead_scores", resource_type="lead_scoring", details={"scored_count": scored}, request=request)
        return {"scored": scored, "message": i18n_message("leads_scored_count", request)}
    except Exception as e:
        db.rollback()
        logger.error(f"Error calculating lead scores: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/lead-scoring/scores", dependencies=[Depends(require_permission("sales.view"))], response_model=List[Dict[str, Any]])
def get_lead_scores(grade: Optional[str] = None, current_user=Depends(get_current_user)):
    """عرض نقاط الفرص مع التصنيف"""
    db = get_db_connection(current_user.company_id)
    try:
        conditions = ["1=1"]
        params = {}
        if grade:
            conditions.append("ls.grade = :grade")
            params["grade"] = grade.upper()

        rows = db.execute(text(f"""
            SELECT ls.*, o.title, o.stage, o.expected_value, o.contact_name,
                   p.name as customer_name
            FROM crm_lead_scores ls
            JOIN sales_opportunities o ON ls.opportunity_id = o.id
            LEFT JOIN parties p ON o.customer_id = p.id
            WHERE {' AND '.join(conditions)}
            ORDER BY ls.total_score DESC
        """), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


# ======================== CRM-007: Customer Segmentation ========================

@router.get("/segments", dependencies=[Depends(require_permission("sales.view"))], response_model=List[Dict[str, Any]])
def list_segments(current_user=Depends(get_current_user)):
    """قائمة شرائح العملاء"""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT s.*,
                   (SELECT COUNT(*) FROM crm_customer_segment_members m WHERE m.segment_id = s.id) as member_count
            FROM crm_customer_segments s
            WHERE s.is_active = TRUE
            ORDER BY s.name
        """)).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.post("/segments", status_code=201, dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def create_segment(data: SegmentCreate, request: Request, current_user=Depends(get_current_user)):
    """Create Segment."""
    db = get_db_connection(current_user.company_id)
    try:
        import json
        sid = db.execute(text("""
            INSERT INTO crm_customer_segments (name, description, criteria, color, auto_assign, created_by)
            VALUES (:name, :desc, :criteria, :color, :auto, :uid) RETURNING id
        """), {
            "name": data.name, "desc": data.description,
            "criteria": json.dumps(data.criteria or {}),
            "color": data.color, "auto": data.auto_assign, "uid": current_user.id
        }).scalar()
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_create_segment", resource_type="customer_segment", resource_id=str(sid), details={"name": data.name}, request=request)
        return {"id": sid, "message": i18n_message("segment_created", request)}
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating segment: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/segments/{seg_id}", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def update_segment(seg_id: int, data: SegmentUpdate, request: Request, current_user=Depends(get_current_user)):
    """Update Segment."""
    db = get_db_connection(current_user.company_id)
    try:
        import json
        updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
        if "criteria" in updates:
            updates["criteria"] = json.dumps(updates["criteria"])
        if not updates:
            raise HTTPException(**http_error(400, "no_data"))
        updates["id"] = seg_id
        validate_update_keys(k for k in updates if k != "id")  # T2.2 defense-in-depth
        set_clause = ", ".join(f"{k} = :{k}" for k in updates if k != "id")
        db.execute(text(f"UPDATE crm_customer_segments SET {set_clause}, updated_at = NOW() WHERE id = :id"), updates)
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_update_segment", resource_type="customer_segment", resource_id=str(seg_id), details={"fields_updated": list(updates.keys())}, request=request)
        return {"message": i18n_message("webhook_updated_success", request)}
    finally:
        db.close()


@router.delete("/segments/{seg_id}", dependencies=[Depends(require_permission("sales.delete"))], response_model=Dict[str, Any])
def delete_segment(seg_id: int, request: Request, current_user=Depends(get_current_user)):
    """Delete Segment."""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("DELETE FROM crm_customer_segment_members WHERE segment_id = :id"), {"id": seg_id})
        db.execute(text("DELETE FROM crm_customer_segments WHERE id = :id"), {"id": seg_id})
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_delete_segment", resource_type="customer_segment", resource_id=str(seg_id), details={}, request=request)
        return {"message": i18n_message("webhook_deleted_success", request)}
    finally:
        db.close()


@router.post("/segments/{seg_id}/customers/{customer_id}",
             status_code=201, dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def add_customer_to_segment(seg_id: int, customer_id: int, request: Request, current_user=Depends(get_current_user)):
    """Add Customer To Segment."""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("""
            INSERT INTO crm_customer_segment_members (segment_id, customer_id)
            VALUES (:sid, :cid) ON CONFLICT DO NOTHING
        """), {"sid": seg_id, "cid": customer_id})
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_add_customer_to_segment", resource_type="customer_segment", resource_id=str(seg_id), details={"customer_id": customer_id}, request=request)
        return {"message": i18n_message("segment_member_added", request)}
    except Exception as e:
        db.rollback()
        logger.error(f"Error adding customer to segment: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.delete("/segments/{seg_id}/customers/{customer_id}",
               dependencies=[Depends(require_permission("sales.delete"))], response_model=Dict[str, Any])
def remove_customer_from_segment(seg_id: int, customer_id: int, request: Request, current_user=Depends(get_current_user)):
    """Remove Customer From Segment."""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("""
            DELETE FROM crm_customer_segment_members WHERE segment_id = :sid AND customer_id = :cid
        """), {"sid": seg_id, "cid": customer_id})
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_remove_customer_from_segment", resource_type="customer_segment", resource_id=str(seg_id), details={"customer_id": customer_id}, request=request)
        return {"message": i18n_message("segment_member_removed", request)}
    finally:
        db.close()


@router.get("/segments/{seg_id}/customers", dependencies=[Depends(require_permission("sales.view"))], response_model=List[Dict[str, Any]])
def get_segment_customers(seg_id: int, current_user=Depends(get_current_user)):
    """Get Segment Customers."""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT p.id, p.name, p.email, p.phone, p.party_type, m.added_at
            FROM crm_customer_segment_members m
            JOIN parties p ON m.customer_id = p.id
            WHERE m.segment_id = :sid
            ORDER BY m.added_at DESC
        """), {"sid": seg_id}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


# ======================== CRM-008: CRM Contacts ========================


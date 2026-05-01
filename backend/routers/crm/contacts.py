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

from .core import ContactCreate, ContactUpdate

@router.get("/contacts", dependencies=[Depends(require_permission("sales.view"))], response_model=List[Dict[str, Any]])
def list_contacts(customer_id: Optional[int] = None, current_user=Depends(get_current_user)):
    """قائمة جهات الاتصال"""
    db = get_db_connection(current_user.company_id)
    try:
        conditions = ["1=1"]
        params = {}
        if customer_id:
            conditions.append("c.customer_id = :cid")
            params["cid"] = customer_id

        rows = db.execute(text(f"""
            SELECT c.*, p.name as customer_name
            FROM crm_contacts c
            LEFT JOIN parties p ON c.customer_id = p.id
            WHERE {' AND '.join(conditions)}
            ORDER BY c.is_primary DESC, c.first_name
        """), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.post("/contacts", status_code=201, dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def create_contact(data: ContactCreate, request: Request, current_user=Depends(get_current_user)):
    """Create Contact."""
    db = get_db_connection(current_user.company_id)
    try:
        # If setting as primary, unset others
        if data.is_primary:
            db.execute(text("UPDATE crm_contacts SET is_primary = FALSE WHERE customer_id = :cid"),
                       {"cid": data.customer_id})

        cid = db.execute(text("""
            INSERT INTO crm_contacts (
                customer_id, first_name, last_name, job_title,
                email, phone, mobile, department,
                is_primary, is_decision_maker, notes, created_by
            ) VALUES (
                :cust, :fname, :lname, :title,
                :email, :phone, :mobile, :dept,
                :primary, :decision, :notes, :uid
            ) RETURNING id
        """), {
            "cust": data.customer_id, "fname": data.first_name,
            "lname": data.last_name, "title": data.job_title,
            "email": data.email, "phone": data.phone,
            "mobile": data.mobile, "dept": data.department,
            "primary": data.is_primary, "decision": data.is_decision_maker,
            "notes": data.notes, "uid": current_user.id
        }).scalar()
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_create_contact", resource_type="contact", resource_id=str(cid), details={"customer_id": data.customer_id, "first_name": data.first_name}, request=request)
        return {"id": cid, "message": "تم إنشاء جهة الاتصال"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating contact: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/contacts/{contact_id}", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def update_contact(contact_id: int, data: ContactUpdate, request: Request, current_user=Depends(get_current_user)):
    """Update Contact."""
    db = get_db_connection(current_user.company_id)
    try:
        updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
        if not updates:
            raise HTTPException(**http_error(400, "no_data"))

        # If setting as primary, unset others for same customer  
        if updates.get("is_primary"):
            contact = db.execute(text("SELECT customer_id FROM crm_contacts WHERE id = :id"),
                                 {"id": contact_id}).fetchone()
            if contact:
                db.execute(text("UPDATE crm_contacts SET is_primary = FALSE WHERE customer_id = :cid"),
                           {"cid": contact.customer_id})

        updates["id"] = contact_id
        validate_update_keys(k for k in updates if k != "id")  # T2.2 defense-in-depth
        set_clause = ", ".join(f"{k} = :{k}" for k in updates if k != "id")
        db.execute(text(f"UPDATE crm_contacts SET {set_clause}, updated_at = NOW() WHERE id = :id"), updates)
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_update_contact", resource_type="contact", resource_id=str(contact_id), details={"fields_updated": list(updates.keys())}, request=request)
        return {"message": "تم التحديث"}
    finally:
        db.close()


@router.delete("/contacts/{contact_id}", dependencies=[Depends(require_permission("sales.delete"))], response_model=Dict[str, Any])
def delete_contact(contact_id: int, request: Request, current_user=Depends(get_current_user)):
    """Delete Contact."""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("DELETE FROM crm_contacts WHERE id = :id"), {"id": contact_id})
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_delete_contact", resource_type="contact", resource_id=str(contact_id), details={}, request=request)
        return {"message": "تم الحذف"}
    finally:
        db.close()


# ======================== CRM-009: Pipeline Analytics & Dashboard ========================


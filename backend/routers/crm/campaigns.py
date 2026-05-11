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
from utils.permissions import branch_scope_filter, require_permission, require_module, validate_branch_access
from utils.accounting import generate_sequential_number
from utils.audit import log_activity
from utils.sql_builder import validate_update_keys
from services.notification_service import notification_service
from schemas.campaign import CampaignCreate, TrackingWebhookPayload

logger = logging.getLogger(__name__)

router = APIRouter()

from .core import CampaignUpdate

@router.get("/campaigns", dependencies=[Depends(require_permission("crm.campaign_view"))], response_model=List[Dict[str, Any]])
def list_campaigns(
    status: Optional[str] = None,
    campaign_type: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user=Depends(get_current_user)
):
    """List Campaigns."""
    db = get_db_connection(current_user.company_id)
    try:
        conditions = ["1=1"]
        params = {}
        branch_clause = branch_scope_filter(current_user, branch_id, "c.branch_id", params)
        if branch_clause:
            conditions.append(branch_clause[4:].strip() if branch_clause.startswith("AND ") else branch_clause.strip())
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if campaign_type:
            conditions.append("campaign_type = :type")
            params["type"] = campaign_type

        rows = db.execute(text(f"""
            SELECT c.*, u.full_name as created_by_name
            FROM marketing_campaigns c
            LEFT JOIN company_users u ON c.created_by = u.id
            WHERE {' AND '.join(conditions)}
            ORDER BY c.created_at DESC
        """), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.get("/campaigns/{campaign_id}", dependencies=[Depends(require_permission("crm.campaign_view"))], response_model=Dict[str, Any])
def get_campaign(campaign_id: int, current_user=Depends(get_current_user)):
    """Get Campaign."""
    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(text("""
            SELECT c.*, s.name as segment_name
            FROM marketing_campaigns c
            LEFT JOIN crm_customer_segments s ON c.segment_id = s.id
            WHERE c.id = :id
        """), {"id": campaign_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "campaign_not_found", request))
        data = dict(row._mapping)
        # Compute rates
        sent = data.get("total_sent") or 0
        data["delivery_rate"] = round(100.0 * (data.get("total_delivered") or 0) / sent, 1) if sent else 0
        data["open_rate"] = round(100.0 * (data.get("total_opened") or 0) / sent, 1) if sent else 0
        data["click_rate"] = round(100.0 * (data.get("total_clicked") or 0) / sent, 1) if sent else 0
        data["response_rate"] = round(100.0 * (data.get("total_responded") or 0) / sent, 1) if sent else 0
        responded = data.get("total_responded") or 0
        cost = float(data.get("actual_cost") or data.get("estimated_cost") or 0)
        data["cost_per_lead"] = round(cost / responded, 2) if responded and cost else 0
        return data
    finally:
        db.close()


@router.post("/campaigns", status_code=201, dependencies=[Depends(require_permission("crm.campaign_manage"))], response_model=Dict[str, Any])
def create_campaign(data: CampaignCreate, request: Request, current_user=Depends(get_current_user)):
    """Create Campaign."""
    db = get_db_connection(current_user.company_id)
    try:
        cid = db.execute(text("""
            INSERT INTO marketing_campaigns (
                name, campaign_type, status, start_date, end_date,
                budget, target_audience, description, created_by, branch_id,
                segment_id, subject, content, scheduled_date, estimated_cost
            ) VALUES (
                :name, :type, :status, :start, :end,
                :budget, :audience, :desc, :uid, :branch,
                :segment_id, :subject, :content,
                CASE WHEN :scheduled IS NOT NULL THEN :scheduled::timestamptz ELSE NULL END,
                :est_cost
            ) RETURNING id
        """), {
            "name": data.name, "type": data.campaign_type, "status": data.status,
            "start": data.start_date, "end": data.end_date,
            "budget": data.budget, "audience": data.target_audience,
            "desc": data.description, "uid": current_user.id, "branch": data.branch_id,
            "segment_id": data.segment_id, "subject": data.subject,
            "content": data.content, "scheduled": data.scheduled_date,
            "est_cost": data.estimated_cost,
        }).scalar()
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_create_campaign", resource_type="campaign", resource_id=str(cid), details={"name": data.name, "campaign_type": data.campaign_type}, request=request)
        return {"id": cid, "message": i18n_message("campaign_created", request)}
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating campaign: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/campaigns/{campaign_id}", dependencies=[Depends(require_permission("crm.campaign_manage"))], response_model=Dict[str, Any])
def update_campaign(campaign_id: int, data: CampaignUpdate, request: Request, current_user=Depends(get_current_user)):
    """Update Campaign."""
    db = get_db_connection(current_user.company_id)
    try:
        updates = {k: v for k, v in data.dict(exclude_unset=True).items() if v is not None}
        if not updates:
            raise HTTPException(**http_error(400, "no_data_to_update"))
        updates["id"] = campaign_id
        validate_update_keys(k for k in updates if k != "id")  # T2.2 defense-in-depth
        set_clause = ", ".join(f"{k} = :{k}" for k in updates if k != "id")
        db.execute(text(f"UPDATE marketing_campaigns SET {set_clause}, updated_at = NOW() WHERE id = :id"), updates)
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_update_campaign", resource_type="campaign", resource_id=str(campaign_id), details={"fields_updated": list(updates.keys())}, request=request)
        return {"message": i18n_message(("campaign_updated", request))}
    finally:
        db.close()


@router.delete("/campaigns/{campaign_id}", dependencies=[Depends(require_permission("crm.campaign_manage"))], response_model=Dict[str, Any])
def delete_campaign(campaign_id: int, request: Request, current_user=Depends(get_current_user)):
    """Delete Campaign."""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("DELETE FROM marketing_campaigns WHERE id = :id"), {"id": campaign_id})
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_delete_campaign", resource_type="campaign", resource_id=str(campaign_id), details={}, request=request)
        return {"message": i18n_message(("campaign_deleted", request))}
    finally:
        db.close()


# ---- Campaign Execution ----

@router.post("/campaigns/{campaign_id}/execute", dependencies=[Depends(require_permission("crm.campaign_execute"))], response_model=Dict[str, Any])
async def execute_campaign(campaign_id: int, request: Request, current_user=Depends(get_current_user)):
    """Execute campaign: fetch segment contacts, create recipient records, dispatch notifications."""
    db = get_db_connection(current_user.company_id)
    try:
        # CRM-F2: lock the campaign row for the duration of execution
        # so concurrent /execute calls can't both pass the idempotency
        # check and double-insert recipients.
        campaign = db.execute(text("""
            SELECT id, segment_id, campaign_type, subject, content, status, created_by
            FROM marketing_campaigns WHERE id = :id
            FOR UPDATE
        """), {"id": campaign_id}).fetchone()

        if not campaign:
            raise HTTPException(**http_error(404, "campaign_not_found", request))

        c = dict(campaign._mapping)
        if c["status"] not in ("draft", "scheduled"):
            raise HTTPException(**http_error(400, "campaign_must_be_in_draft_or_scheduled_status_to_e", request))

        if not c["segment_id"]:
            raise HTTPException(**http_error(400, "campaign_must_have_a_segment_to_execute", request))

        # CRM-F2: Idempotency — prevent double-execution (backed by the
        # row-level lock above so two concurrent requests serialize here).
        existing_recipients = db.execute(text(
            "SELECT COUNT(*) FROM campaign_recipients WHERE campaign_id = :id"
        ), {"id": campaign_id}).scalar()
        if existing_recipients > 0:
            raise HTTPException(**http_error(400, "campaign_already_has_recipients__it_may_have_been_", request))

        # Fetch segment contacts
        contacts = db.execute(text("""
            SELECT p.id, p.name, p.email, p.phone
            FROM crm_customer_segment_members csm
            JOIN parties p ON csm.customer_id = p.id
            WHERE csm.segment_id = :seg_id
        """), {"seg_id": c["segment_id"]}).fetchall()

        if not contacts:
            raise HTTPException(**http_error(400, "no_contacts_found_in_the_target_segment", request))

        campaign_type = c["campaign_type"] or "email"
        total_created = 0

        for contact in contacts:
            ct = dict(contact._mapping)
            channels = []
            if campaign_type in ("email", "both") and ct.get("email"):
                channels.append("email")
            if campaign_type in ("sms", "both") and ct.get("phone"):
                channels.append("sms")

            for channel in channels:
                db.execute(text("""
                    INSERT INTO campaign_recipients (campaign_id, contact_id, channel, delivery_status)
                    VALUES (:cid, :contact_id, :channel, 'sent')
                """), {"cid": campaign_id, "contact_id": ct["id"], "channel": channel})
                total_created += 1

        # Update campaign status and metrics
        db.execute(text("""
            UPDATE marketing_campaigns
            SET status = 'executing', executed_at = NOW(),
                total_sent = :total, updated_at = NOW()
            WHERE id = :id
        """), {"total": total_created, "id": campaign_id})

        # Mark as completed (synchronous execution)
        db.execute(text("""
            UPDATE marketing_campaigns
            SET status = 'completed', total_delivered = :total,
                updated_at = NOW()
            WHERE id = :id
        """), {"total": total_created, "id": campaign_id})

        # Update recipient delivery status
        db.execute(text("""
            UPDATE campaign_recipients
            SET delivery_status = 'delivered', updated_at = NOW()
            WHERE campaign_id = :cid AND delivery_status = 'sent'
        """), {"cid": campaign_id})

        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_execute_campaign", resource_type="campaign", resource_id=str(campaign_id), details={"total_recipients": total_created}, request=request)

        # Notify campaign creator about execution completion
        campaign_creator = c.get("created_by")
        if campaign_creator:
            try:
                await notification_service.dispatch(
                    db=get_db_connection(current_user.company_id),
                    company_id=current_user.company_id,
                    recipient_id=campaign_creator,
                    event_type="crm.campaign_executed",
                    title="تم تنفيذ الحملة التسويقية",
                    body=f"تم إرسال الحملة #{campaign_id} إلى {total_created} مستلم",
                    feature_source="crm",
                    reference_type="campaign",
                    reference_id=campaign_id,
                    link=f"/campaigns/{campaign_id}/report",
                )
            except Exception as notif_err:
                logger.warning("Failed to dispatch campaign execution notification: %s", notif_err)

        return {
            "message": i18n_message("campaign_executed", request),
            "total_recipients": total_created,
            "campaign_id": campaign_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to execute campaign: {e}")
        raise HTTPException(**http_error(500, "failed_to_execute_campaign", request))
    finally:
        db.close()


@router.get("/campaigns/{campaign_id}/recipients", dependencies=[Depends(require_permission("crm.campaign_view"))], response_model=Dict[str, Any])
def list_campaign_recipients(
    campaign_id: int,
    delivery_status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user=Depends(get_current_user),
):
    """List recipients for a campaign with their engagement status."""
    db = get_db_connection(current_user.company_id)
    try:
        conditions = ["cr.campaign_id = :cid"]
        params: dict = {"cid": campaign_id, "skip": skip, "limit": limit}

        if delivery_status:
            conditions.append("cr.delivery_status = :ds")
            params["ds"] = delivery_status

        where = " AND ".join(conditions)
        rows = db.execute(text(f"""
            SELECT cr.id, cr.contact_id, p.name as contact_name, p.email as contact_email,
                   cr.channel, cr.delivery_status, cr.opened_at, cr.clicked_at, cr.responded_at,
                   cr.created_at
            FROM campaign_recipients cr
            JOIN parties p ON cr.contact_id = p.id
            WHERE {where}
            ORDER BY cr.created_at DESC
            OFFSET :skip LIMIT :limit
        """), params).fetchall()

        count_row = db.execute(text(f"""
            SELECT COUNT(*) FROM campaign_recipients cr WHERE {where}
        """), params).fetchone()

        return {
            "recipients": [dict(r._mapping) for r in rows],
            "total": count_row[0] if count_row else 0,
        }
    finally:
        db.close()


@router.post("/campaigns/webhook/track", response_model=Dict[str, Any])
def campaign_tracking_webhook(payload: TrackingWebhookPayload, company_id: str):
    """Public webhook for tracking campaign engagement (opens, clicks, responses).
    Requires company_id query param. Validates a signed payload to prevent tampering."""
    import hashlib
    import os
    import hmac as hmac_lib
    webhook_secret = os.environ.get("CAMPAIGN_WEBHOOK_SECRET")
    if not webhook_secret:
        raise HTTPException(**http_error(500, "webhook_secret_not_configured", request))
    expected_sig = hashlib.sha256(f"{payload.recipient_id}:{payload.event}:{webhook_secret}".encode()).hexdigest()

    if not hmac_lib.compare_digest(expected_sig, payload.signature):
        raise HTTPException(**http_error(403, "invalid_signature", request))

    db = get_db_connection(company_id)
    try:
        if payload.event == "delivered":
            db.execute(text("""
                UPDATE campaign_recipients SET delivery_status = 'delivered', updated_at = NOW()
                WHERE id = :rid
            """), {"rid": payload.recipient_id})
            db.execute(text("""
                UPDATE marketing_campaigns SET total_delivered = total_delivered + 1
                WHERE id = (SELECT campaign_id FROM campaign_recipients WHERE id = :rid)
            """), {"rid": payload.recipient_id})

        elif payload.event == "opened":
            db.execute(text("""
                UPDATE campaign_recipients SET opened_at = COALESCE(opened_at, NOW()), updated_at = NOW()
                WHERE id = :rid
            """), {"rid": payload.recipient_id})
            db.execute(text("""
                UPDATE marketing_campaigns SET total_opened = total_opened + 1
                WHERE id = (SELECT campaign_id FROM campaign_recipients WHERE id = :rid)
            """), {"rid": payload.recipient_id})

        elif payload.event == "clicked":
            db.execute(text("""
                UPDATE campaign_recipients SET clicked_at = COALESCE(clicked_at, NOW()), updated_at = NOW()
                WHERE id = :rid
            """), {"rid": payload.recipient_id})
            db.execute(text("""
                UPDATE marketing_campaigns SET total_clicked = total_clicked + 1
                WHERE id = (SELECT campaign_id FROM campaign_recipients WHERE id = :rid)
            """), {"rid": payload.recipient_id})

        elif payload.event == "responded":
            db.execute(text("""
                UPDATE campaign_recipients SET responded_at = COALESCE(responded_at, NOW()), updated_at = NOW()
                WHERE id = :rid
            """), {"rid": payload.recipient_id})
            db.execute(text("""
                UPDATE marketing_campaigns SET total_responded = total_responded + 1
                WHERE id = (SELECT campaign_id FROM campaign_recipients WHERE id = :rid)
            """), {"rid": payload.recipient_id})

        elif payload.event in ("bounced", "failed"):
            db.execute(text("""
                UPDATE campaign_recipients SET delivery_status = :status, updated_at = NOW()
                WHERE id = :rid
            """), {"rid": payload.recipient_id, "status": payload.event})

        db.commit()
        return {"status": "ok"}
    except Exception as e:
        db.rollback()
        logger.error(f"Tracking webhook error: {e}")
        raise HTTPException(**http_error(500, "tracking_webhook_failed", request))
    finally:
        db.close()


# ---- Lead Attribution ----

@router.post("/campaigns/{campaign_id}/attribute-lead", dependencies=[Depends(require_permission("crm.campaign_manage"))], response_model=Dict[str, Any])
def attribute_lead_to_campaign(campaign_id: int, lead_id: int, request: Request, current_user=Depends(get_current_user)):
    """Attribute a CRM lead/opportunity to a campaign."""
    db = get_db_connection(current_user.company_id)
    try:
        # Verify campaign exists
        campaign = db.execute(text("SELECT id FROM marketing_campaigns WHERE id = :id"), {"id": campaign_id}).fetchone()
        if not campaign:
            raise HTTPException(**http_error(404, "campaign_not_found", request))

        # Verify lead exists
        lead = db.execute(text("SELECT id FROM sales_opportunities WHERE id = :id"), {"id": lead_id}).fetchone()
        if not lead:
            raise HTTPException(**http_error(404, "leadopportunity_not_found", request))

        # Check for duplicate
        existing = db.execute(text("""
            SELECT id FROM campaign_lead_attributions
            WHERE campaign_id = :cid AND lead_id = :lid
        """), {"cid": campaign_id, "lid": lead_id}).fetchone()
        if existing:
            raise HTTPException(**http_error(400, "lead_already_attributed_to_this_campaign", request))

        db.execute(text("""
            INSERT INTO campaign_lead_attributions (campaign_id, lead_id, attributed_at)
            VALUES (:cid, :lid, NOW())
        """), {"cid": campaign_id, "lid": lead_id})

        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_attribute_lead_to_campaign", resource_type="campaign_lead_attribution", resource_id=str(campaign_id), details={"lead_id": lead_id}, request=request)
        return {"message": i18n_message("lead_attributed_to_campaign", request), "campaign_id": campaign_id, "lead_id": lead_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Lead attribution error: {e}")
        raise HTTPException(**http_error(500, "failed_to_attribute_lead", request))
    finally:
        db.close()


@router.get("/campaigns/{campaign_id}/metrics", dependencies=[Depends(require_permission("crm.campaign_view"))], response_model=Dict[str, Any])
def get_campaign_metrics(campaign_id: int, current_user=Depends(get_current_user)):
    """Get detailed engagement metrics and lead attribution for a campaign."""
    db = get_db_connection(current_user.company_id)
    try:
        campaign = db.execute(text("""
            SELECT c.id, c.name, c.total_sent, c.total_delivered, c.total_opened,
                   c.total_clicked, c.total_responded, c.estimated_cost, c.actual_cost
            FROM marketing_campaigns c WHERE c.id = :id
        """), {"id": campaign_id}).fetchone()
        if not campaign:
            raise HTTPException(**http_error(404, "campaign_not_found", request))

        c = dict(campaign._mapping)
        sent = c["total_sent"] or 0
        c["delivery_rate"] = round(100.0 * (c["total_delivered"] or 0) / sent, 1) if sent else 0
        c["open_rate"] = round(100.0 * (c["total_opened"] or 0) / sent, 1) if sent else 0
        c["click_rate"] = round(100.0 * (c["total_clicked"] or 0) / sent, 1) if sent else 0
        c["response_rate"] = round(100.0 * (c["total_responded"] or 0) / sent, 1) if sent else 0

        # Attributed leads
        leads = db.execute(text("""
            SELECT cla.id, cla.lead_id, so.title as lead_title, so.stage,
                   so.expected_value, cla.attributed_at
            FROM campaign_lead_attributions cla
            JOIN sales_opportunities so ON cla.lead_id = so.id
            WHERE cla.campaign_id = :cid
            ORDER BY cla.attributed_at DESC
        """), {"cid": campaign_id}).fetchall()

        responded = c["total_responded"] or 0
        cost = float(c.get("actual_cost") or c.get("estimated_cost") or 0)
        c["cost_per_lead"] = round(cost / responded, 2) if responded and cost else 0
        c["attributed_leads"] = [dict(r._mapping) for r in leads]
        c["total_attributed_leads"] = len(leads)

        return c
    finally:
        db.close()


# ======================== CRM-005: Knowledge Base ========================


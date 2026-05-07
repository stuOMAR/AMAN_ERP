"""
AMAN ERP — Recurring Template Review Queue Router
Admin endpoints for the recurring JE pending-review queue.

Sensitive: admin.recurring, critical=True
Contract: specs/022-audit-security-finance-integrity/contracts/http-endpoints.md
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import get_db_connection
from routers.auth import get_current_user
from services.permissions.sensitive import require_sensitive_permission

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/recurring",
    tags=["Admin Recurring Review"],
)


# ── Schemas ────────────────────────────────────────────────────────────────────


class RejectBody(BaseModel):
    reason: str = Field(..., min_length=1)


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get(
    "/pending",
    response_model=List[Dict[str, Any]],
    dependencies=[Depends(require_sensitive_permission("admin.recurring", critical=True))],
)
def list_pending_reviews(
    current_user: dict = Depends(get_current_user),
):
    """List recurring JE entries pending review."""
    tenant_id = current_user.get("tenant_id") or current_user.get("company_id")
    conn = get_db_connection(current_user["company_id"])
    try:
        rows = conn.execute(
            text("""
                SELECT r.id, r.template_id, r.amount, r.expense_category_id,
                       r.lines, r.run_date, r.status, r.created_at,
                       r.approved_by, r.approved_at,
                       r.rejected_by, r.rejected_at, r.rejection_reason,
                       t.description AS template_description
                  FROM recurring_je_pending_review r
                  LEFT JOIN recurring_journal_templates t ON r.template_id = t.id
                 WHERE r.tenant_id = :tnt
                   AND r.status = 'pending'
                 ORDER BY r.created_at DESC
            """),
            {"tnt": tenant_id},
        ).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        conn.close()


@router.post(
    "/pending/{pending_id}/approve",
    response_model=Dict[str, Any],
    dependencies=[Depends(require_sensitive_permission("admin.recurring", critical=True))],
)
def approve_pending_review(
    pending_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Approve a pending recurring JE and post it via gl_service."""
    tenant_id = current_user.get("tenant_id") or current_user.get("company_id")
    actor_id = current_user.get("id")

    conn = get_db_connection(current_user["company_id"])
    try:
        from services.recurring_je_service import approve_pending

        result = approve_pending(conn, tenant_id, pending_id, actor_id=actor_id)
        conn.commit()
        return {
            "posted": result.posted,
            "pending_review_id": result.pending_review_id,
            "journal_entry_id": result.journal_entry_id,
        }
    except ValueError as e:
        conn.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        conn.rollback()
        logger.exception("Failed to approve pending review %s", pending_id)
        raise HTTPException(status_code=500, detail="Approval failed")
    finally:
        conn.close()


@router.post(
    "/pending/{pending_id}/reject",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_sensitive_permission("admin.recurring", critical=True))],
)
def reject_pending_review(
    pending_id: int,
    body: RejectBody,
    current_user: dict = Depends(get_current_user),
):
    """Reject a pending recurring JE with a reason."""
    tenant_id = current_user.get("tenant_id") or current_user.get("company_id")
    actor_id = current_user.get("id")

    conn = get_db_connection(current_user["company_id"])
    try:
        from services.recurring_je_service import reject_pending

        reject_pending(conn, tenant_id, pending_id, actor_id=actor_id, reason=body.reason)
        conn.commit()
        return {"status": "rejected", "id": pending_id}
    except ValueError as e:
        conn.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        conn.rollback()
        logger.exception("Failed to reject pending review %s", pending_id)
        raise HTTPException(status_code=500, detail="Rejection failed")
    finally:
        conn.close()

"""Employee Receipt Settlement Router.

Endpoints for the four state transitions:
  POST /hr/employee-receipts           — submit (draft → submitted)
  POST /hr/employee-receipts/{id}/approve — approve (submitted → approved)
  POST /hr/employee-receipts/{id}/reject  — reject (submitted → draft)
  POST /hr/employee-receipts/{id}/post    — post (approved → posted, creates JE)

Sensitive: finance.expenses, critical=True
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import Request, APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import get_db_connection
from routers.auth import get_current_user
from services.permissions.sensitive import require_sensitive_permission
from utils.i18n import http_error, i18n_message

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/hr/employee-receipts",
    tags=["HR Employee Receipts"],
)


# ── Schemas ────────────────────────────────────────────────────────────────────

class SettlementCreate(BaseModel):
    employee_id: int
    advance_id: int
    receipt_id: int
    amount: Decimal = Field(..., gt=0)


class RejectBody(BaseModel):
    reason: str = Field(..., min_length=1)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=List[Dict[str, Any]],
    dependencies=[Depends(require_sensitive_permission("finance.expenses", critical=True))],
)
def list_settlements(
    status_filter: Optional[str] = None,
    employee_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
):
    """List employee receipt settlements with optional filters."""
    tenant_id = current_user.get("tenant_id") or current_user.get("company_id")
    conn = get_db_connection(current_user["company_id"])
    try:
        query = "SELECT * FROM employee_receipt_settlements WHERE tenant_id = :tnt"
        params: dict = {"tnt": tenant_id}
        if status_filter:
            query += " AND status = :st"
            params["st"] = status_filter
        if employee_id:
            query += " AND employee_id = :eid"
            params["eid"] = employee_id
        query += " ORDER BY id DESC"
        rows = conn.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        conn.close()


@router.post(
    "",
    response_model=Dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_sensitive_permission("finance.expenses", critical=True))],
)
def submit_settlement(request: Request, 
    payload: SettlementCreate,
    current_user: dict = Depends(get_current_user),
):
    """Create and submit a new employee receipt settlement."""
    tenant_id = current_user.get("tenant_id") or current_user.get("company_id")
    conn = get_db_connection(current_user["company_id"])
    try:
        from services.employee_receipt_service import submit_settlement
        result = submit_settlement(
            conn, tenant_id, payload.employee_id,
            payload.advance_id, payload.receipt_id, payload.amount,
        )
        conn.commit()
        return result
    except ValueError as e:
        conn.rollback()
        logger.exception("Validation error in submit_settlement")
        raise HTTPException(status_code=400, detail=i18n_message("validation_error", request) if request else "Validation error")
        raise HTTPException(**http_error(500, "submission_failed", request))
    finally:
        conn.close()


@router.post(
    "/{settlement_id}/approve",
    response_model=Dict[str, Any],
    dependencies=[Depends(require_sensitive_permission("finance.expenses", critical=True))],
)
def approve_settlement(request: Request, 
    settlement_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Approve a submitted settlement."""
    tenant_id = current_user.get("tenant_id") or current_user.get("company_id")
    actor_id = current_user.get("id")
    conn = get_db_connection(current_user["company_id"])
    try:
        from services.employee_receipt_service import approve_settlement
        result = approve_settlement(conn, tenant_id, settlement_id, actor_id)
        conn.commit()
        return result
    except ValueError as e:
        conn.rollback()
        logger.exception("Validation error in approve_settlement %s", settlement_id)
        raise HTTPException(status_code=400, detail=i18n_message("validation_error", request) if request else "Validation error")
    except Exception:
        conn.rollback()
        logger.exception("Failed to approve settlement %s", settlement_id)
        raise HTTPException(**http_error(500, "approval_failed", request))
    finally:
        conn.close()


@router.post(
    "/{settlement_id}/reject",
    response_model=Dict[str, Any],
    dependencies=[Depends(require_sensitive_permission("finance.expenses", critical=True))],
)
def reject_settlement(request: Request, 
    settlement_id: int,
    body: RejectBody,
    current_user: dict = Depends(get_current_user),
):
    """Reject a submitted settlement."""
    tenant_id = current_user.get("tenant_id") or current_user.get("company_id")
    actor_id = current_user.get("id")
    conn = get_db_connection(current_user["company_id"])
    try:
        from services.employee_receipt_service import reject_settlement
        reject_settlement(conn, tenant_id, settlement_id, actor_id, body.reason)
        conn.commit()
        return {"status": "rejected", "id": settlement_id}
    except ValueError as e:
        conn.rollback()
        logger.exception("Validation error in reject_settlement %s", settlement_id)
        raise HTTPException(status_code=400, detail=i18n_message("validation_error", request) if request else "Validation error")
    except Exception:
        conn.rollback()
        logger.exception("Failed to reject settlement %s", settlement_id)
        raise HTTPException(**http_error(500, "rejection_failed", request))
    finally:
        conn.close()


@router.post(
    "/{settlement_id}/post",
    response_model=Dict[str, Any],
    dependencies=[Depends(require_sensitive_permission("finance.expenses", critical=True))],
)
def post_settlement(request: Request, 
    settlement_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Post an approved settlement — creates a journal entry via gl_service."""
    tenant_id = current_user.get("tenant_id") or current_user.get("company_id")
    actor_id = current_user.get("id")
    conn = get_db_connection(current_user["company_id"])
    try:
        from services.employee_receipt_service import post_settlement
        result = post_settlement(conn, tenant_id, settlement_id, actor_id)
        conn.commit()
        return result
    except ValueError as e:
        conn.rollback()
        logger.exception("Validation error in post_settlement %s", settlement_id)
        raise HTTPException(status_code=400, detail=i18n_message("validation_error", request) if request else "Validation error")
    except Exception:
        conn.rollback()
        logger.exception("Failed to post settlement %s", settlement_id)
        raise HTTPException(**http_error(500, "posting_failed", request))
    finally:
        conn.close()

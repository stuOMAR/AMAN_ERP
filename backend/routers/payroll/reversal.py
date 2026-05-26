"""Payroll reversal endpoint.

POST /api/payroll/periods/{id}/reverse — reverse a locked payroll period.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from database import get_db_connection
from services.payroll.period_reversal import reverse_payroll_period
from services.permissions.sensitive import require_sensitive_permission
from utils.i18n import i18n_message

router = APIRouter(prefix="/api/payroll/periods", tags=["Payroll"])
logger = logging.getLogger(__name__)


class ReversalRequest(BaseModel):
    reason: str
    run_id: Optional[int] = None


def _get_tenant_id(current_user) -> str:
    return str(
        current_user.get("company_id")
        if isinstance(current_user, dict)
        else getattr(current_user, "company_id", 0)
    )


def _get_user_id(current_user) -> int:
    return (
        current_user.get("id")
        if isinstance(current_user, dict)
        else getattr(current_user, "id", 0)
    )


@router.post("/{period_id}/reverse")
def reverse_period(
    period_id: int,
    body: ReversalRequest,
    request: Request,
    current_user=Depends(require_sensitive_permission("payroll.reverse")),
):
    """Reverse a locked payroll period."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        result = reverse_payroll_period(
            conn,
            tenant_id=int(tenant_id),
            period_id=period_id,
            run_id=body.run_id,
            reason=body.reason,
            actor_id=_get_user_id(current_user),
        )
        return result
    except LookupError:
        logger.exception("Payroll period not found for reversal")
        raise HTTPException(status_code=404, detail=i18n_message("not_found", request) if request else "Not found")
    except ValueError as e:
        error_code = str(e)
        if error_code == "payroll.period_not_locked":
            logger.exception("Payroll period not locked for reversal")
            raise HTTPException(status_code=422, detail=i18n_message("validation_error", request) if request else "Validation error")
        logger.exception("Validation error in payroll reversal")
        raise HTTPException(status_code=400, detail=i18n_message("validation_error", request) if request else "Validation error")
    finally:
        conn.close()

"""Payroll reversal endpoint.

POST /api/payroll/periods/{id}/reverse — reverse a locked payroll period.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from database import get_db_connection
from services.payroll.period_reversal import reverse_payroll_period
from services.permissions.sensitive import require_sensitive_permission

router = APIRouter(prefix="/api/payroll/periods", tags=["Payroll"])


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
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        detail = str(e)
        if detail == "payroll.period_not_locked":
            raise HTTPException(status_code=422, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    finally:
        conn.close()

"""Bulk salary increment endpoint.

POST /api/hr/employees/bulk-salary-increment — apply salary changes to multiple employees.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional

from database import get_db_connection
from services.hr.bulk_salary_increment import apply_bulk_salary_increment
from services.permissions.sensitive import require_sensitive_permission
from utils.i18n import i18n_message

router = APIRouter(prefix="/api/hr/employees", tags=["HR Salary"])
logger = logging.getLogger(__name__)


class SalaryIncrementRow(BaseModel):
    employee_id: int
    new_salary: Decimal
    increment_amount: Optional[Decimal] = None


class BulkSalaryIncrementRequest(BaseModel):
    rows: List[SalaryIncrementRow]
    effective_date: date
    reason: str
    dry_run: bool = False


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


@router.post("/bulk-salary-increment")
def bulk_salary_increment(
    request: Request,
    body: BulkSalaryIncrementRequest,
    current_user=Depends(require_sensitive_permission("hr.salary.write")),
):
    """Apply bulk salary increments with per-row outcomes."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        result = apply_bulk_salary_increment(
            conn,
            tenant_id=int(tenant_id),
            rows=[r.model_dump() for r in body.rows],
            effective_date=body.effective_date,
            reason=body.reason,
            actor_id=_get_user_id(current_user),
            dry_run=body.dry_run,
        )
        return result
    except Exception as e:
        logger.exception("Error applying bulk salary increment")
        raise HTTPException(status_code=400, detail=i18n_message("internal_error", request) if request else "Internal error")
    finally:
        conn.close()

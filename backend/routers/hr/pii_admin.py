"""HR PII admin endpoints.

GET  /api/hr/employees/{id}/pii       — masked employee with PII fields
PATCH /api/hr/employees/{id}/pii      — update PII fields (encrypts at rest)
GET  /api/hr/employees/{id}/salary-history — salary change audit trail

All endpoints require ``hr.pii`` sensitive permission.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from typing import Optional

from database import get_db_connection
from schemas.hr import EmployeePiiOut
from services.hr.pii import (
    PII_FIELDS,
    decrypt_pii,
    encrypt_pii,
    mask_employee_dict,
    unmask_field,
)
from services.permissions.sensitive import require_sensitive_permission

router = APIRouter(prefix="/api/hr/employees", tags=["HR PII"])


class PiiUpdate(BaseModel):
    field: str
    value: str


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


@router.get("/{employee_id}/pii")
def get_employee_pii(request: Request, 
    employee_id: int,
    current_user=Depends(require_sensitive_permission("hr.pii")),
):
    """Return employee with PII fields masked."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        row = conn.execute(
            text("""
                SELECT id, employee_code, first_name, last_name, email, phone,
                       salary, iban, national_id, passport_number,
                       bank_account_number, gosi_number, status
                FROM employees
                WHERE id = :eid AND tenant_id = :tid
            """),
            {"eid": employee_id, "tid": int(tenant_id)},
        ).fetchone()

        if row is None:
            raise HTTPException(**http_error(404, "employee_not_found", request))

        emp = {
            "id": row[0], "employee_code": row[1],
            "first_name": row[2], "last_name": row[3],
            "email": row[4], "phone": row[5],
            "salary": row[6], "iban": row[7],
            "national_id": row[8], "passport_number": row[9],
            "bank_account_number": row[10], "gosi_number": row[11],
            "status": row[12],
        }
        return mask_employee_dict(emp)
    finally:
        conn.close()


@router.patch("/{employee_id}/pii")
def update_employee_pii(request: Request, 
    employee_id: int,
    body: PiiUpdate,
    current_user=Depends(require_sensitive_permission("hr.pii")),
):
    """Update a single PII field (encrypts at rest)."""
    if body.field not in PII_FIELDS:
        raise HTTPException(status_code=422, detail=i18n_message("unknown_pii_field", request))

    tenant_id = _get_tenant_id(current_user)
    encrypted = encrypt_pii(body.field, body.value, tenant_id=tenant_id)
    encrypted_col = f"{body.field}_encrypted"

    conn = get_db_connection(tenant_id)
    try:
        result = conn.execute(
            text(f"""
                UPDATE employees
                SET {encrypted_col} = :val
                WHERE id = :eid AND tenant_id = :tid
            """),
            {"val": encrypted, "eid": employee_id, "tid": int(tenant_id)},
        )
        if result.rowcount == 0:
            raise HTTPException(**http_error(404, "employee_not_found", request))
        conn.commit()

        # Audit the write
        from services.audit_writer import log_activity
        log_activity(
            conn,
            action="hr.pii.write",
            entity_type="employee",
            entity_id=str(employee_id),
            actor_id=_get_user_id(current_user),
            details={"field": body.field},
            critical=True,
        )
        conn.commit()

        return {"status": "ok", "field": body.field}
    finally:
        conn.close()


@router.get("/{employee_id}/salary-history")
def get_salary_history(
    employee_id: int,
    current_user=Depends(require_sensitive_permission("hr.pii")),
):
    """Return salary change audit trail for an employee."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        rows = conn.execute(
            text("""
                SELECT id, old_salary, new_salary, changed_at, changed_by, reason
                FROM employee_salary_history
                WHERE employee_id = :eid AND tenant_id = :tid
                ORDER BY changed_at DESC
            """),
            {"eid": employee_id, "tid": int(tenant_id)},
        ).fetchall()

        return [
            {
                "id": r[0],
                "old_salary": str(r[1]) if r[1] is not None else None,
                "new_salary": str(r[2]) if r[2] is not None else None,
                "changed_at": r[3].isoformat() if r[3] else None,
                "changed_by": r[4],
                "reason": r[5],
            }
            for r in rows
        ]
    finally:
        conn.close()

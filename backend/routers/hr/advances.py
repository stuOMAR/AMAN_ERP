"""
AMAN ERP — Salary Advances (T15 P1 #71/#72/#104)
السلف على الراتب

A salary advance is a short-term loan against an employee's upcoming
salary. Unlike ``employee_loans`` (which model long-term, multi-installment
loans with interest-free amortisation), advances are typically a single
disbursement with a single deduction in the next 1-3 payroll runs.

Lifecycle:
    pending  → approved   (manager signs off)
             → paid       (treasury pays out + JE posted)
             → recovering (1+ payroll deductions applied)
             → recovered  (full amount recouped)
             → cancelled  (rejected before payment)

The actual payroll-side recovery is wired by ``routers/hr/core/payroll.py``
in :func:`generate_payroll` — see the ``advance_deduction`` column on
``payroll_entries`` and the bulk fetch of active advances.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import hashlib
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from utils.i18n import http_error
from utils.permissions import require_permission, require_module, validate_branch_access, validate_treasury_account_access

router = APIRouter(
    prefix="/hr/advances",
    tags=["Salary Advances"],
    dependencies=[Depends(require_module("hr"))],
)


class AdvanceCreate(BaseModel):
    employee_id: int
    amount: Decimal = Field(..., gt=0)
    installments: int = Field(1, ge=1, le=12)
    reason: Optional[str] = None
    branch_id: Optional[int] = None
    treasury_account_id: Optional[int] = None


class AdvanceApprove(BaseModel):
    treasury_account_id: int


def _approval_idempotency_key(advance_id: int, raw_key: str) -> str:
    digest = hashlib.sha256(f"{advance_id}:{raw_key}".encode("utf-8")).hexdigest()
    return f"hr_adv_pay:{advance_id}:{digest[:32]}"


@router.get("", response_model=List[Dict[str, Any]],
            dependencies=[Depends(require_permission(["hr.view", "hr.loans.view"]))])
def list_advances(employee_id: Optional[int] = None,
                  status_filter: Optional[str] = None,
                  current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        q = "SELECT * FROM salary_advances WHERE 1=1"
        params: Dict[str, Any] = {}
        if employee_id:
            q += " AND employee_id = :eid"
            params["eid"] = employee_id
        if status_filter:
            q += " AND status = :st"
            params["st"] = status_filter
        q += " ORDER BY id DESC"
        rows = db.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


from utils.tax_precision import require_idempotency_key  # noqa: E402


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("hr.loans.manage"))])
def create_advance(payload: AdvanceCreate, request: Request,
                   current_user=Depends(get_current_user)):
    idempotency_key = require_idempotency_key(request, operation="salary advance")
    db = get_db_connection(current_user.company_id)
    try:
        # Check idempotency replay
        existing_adv = db.execute(text("""
            SELECT * FROM salary_advances
            WHERE idempotency_key = :key
            LIMIT 1
        """), {"key": idempotency_key}).fetchone()
        if existing_adv:
            return dict(existing_adv._mapping)

        emp = db.execute(text(
            "SELECT id, salary, branch_id FROM employees WHERE id = :id AND status = 'active'"
        ), {"id": payload.employee_id}).fetchone()
        if not emp:
            raise HTTPException(**http_error(404, "active_employee_not_found", request))
        branch_id = validate_branch_access(current_user, payload.branch_id or emp.branch_id)
        if payload.treasury_account_id:
            validate_treasury_account_access(db, current_user, payload.treasury_account_id, branch_id)

        # Sanity: block advances that exceed 100% of monthly salary.
        if emp.salary and payload.amount > Decimal(str(emp.salary)):
            raise HTTPException(**http_error(400, "advance_exceeds_monthly_salary", request))

        # Block stacked advances (one open at a time per employee).
        open_count = db.execute(text("""
            SELECT COUNT(*) FROM salary_advances
            WHERE employee_id = :eid
              AND status NOT IN ('recovered', 'cancelled')
        """), {"eid": payload.employee_id}).scalar() or 0
        if open_count > 0:
            raise HTTPException(**http_error(400, "employee_has_open_advance", request))

        row = db.execute(text("""
            INSERT INTO salary_advances
                (employee_id, amount, installments, request_date, reason,
                 treasury_account_id, branch_id, status, idempotency_key)
            VALUES (:eid, :amt, :inst, CURRENT_DATE, :reason, :tid, :bid, 'pending', :idempotency_key)
            RETURNING *
        """), {
            "eid": payload.employee_id, "amt": payload.amount,
            "inst": payload.installments, "reason": payload.reason,
            "tid": payload.treasury_account_id,
            "bid": branch_id,
            "idempotency_key": idempotency_key
        }).fetchone()
        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="hr.advance.create", resource_type="salary_advance",
                     resource_id=str(row.id),
                     details={"employee_id": payload.employee_id,
                              "amount": Decimal(str(payload.amount))},
                     request=request, branch_id=branch_id)
        return dict(row._mapping)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.post("/{advance_id}/approve",
             dependencies=[Depends(require_permission("hr.loans.manage"))],
             response_model=Dict[str, Any])
def approve_and_pay(advance_id: int, payload: AdvanceApprove, request: Request,
                    current_user=Depends(get_current_user)):
    """Approve an advance AND post the payment JE in one shot.

    JE: Dr Employee-Advances (asset)   Cr Treasury (cash)

    The ``acc_map_employee_advances`` mapping provides the asset account.
    Falls back to a child of ``11`` (Current Assets) if the mapping is
    absent — emit a warning rather than failing so older tenants can still
    use the feature.
    """
    idempotency_key = require_idempotency_key(request, operation="salary advance approval")
    approval_idempotency_key = _approval_idempotency_key(advance_id, idempotency_key)
    db = get_db_connection(current_user.company_id)
    try:
        adv = db.execute(text(
            "SELECT * FROM salary_advances WHERE id = :id FOR UPDATE"
        ), {"id": advance_id}).fetchone()
        if not adv:
            raise HTTPException(**http_error(404, "advance_not_found", request))
        if adv.status != "pending":
            if adv.status == "paid":
                replay = db.execute(text("""
                    SELECT id FROM journal_entries
                    WHERE idempotency_key = :key
                    LIMIT 1
                """), {"key": approval_idempotency_key}).fetchone()
                if replay:
                    return {"id": advance_id, "status": "paid", "je_id": replay.id, "replayed": True}
            raise HTTPException(status_code=400,
                                detail=f"Advance is not pending (status={adv.status})")
        branch_id = validate_branch_access(current_user, adv.branch_id)

        check_fiscal_period_open(db, date.today().isoformat())

        treasury_account = validate_treasury_account_access(db, current_user, payload.treasury_account_id, branch_id)
        treasury_gl = treasury_account.get("gl_account_id")
        if not treasury_gl:
            raise HTTPException(**http_error(400, "treasury_no_gl_account_hr", request))

        adv_gl = db.execute(text(
            "SELECT acc_id FROM acc_mappings WHERE map_key = 'acc_map_employee_advances' LIMIT 1"
        )).scalar()
        if not adv_gl:
            # Soft fallback: any asset account whose code starts with 113 (other receivables).
            adv_gl = db.execute(text(
                "SELECT id FROM accounts WHERE account_type = 'asset' "
                "AND (account_code LIKE '113%' OR account_number LIKE '113%') "
                "ORDER BY id LIMIT 1"
            )).scalar()
        if not adv_gl:
            raise HTTPException(**http_error(400, "employee_advances_account_not_configured", request))

        from services.gl_service import create_journal_entry
        je_id, _entry_number = create_journal_entry(
            db=db, company_id=current_user.company_id,
            date=date.today().isoformat(),
            description=f"Salary advance — emp {adv.employee_id}",
            lines=[
                {"account_id": adv_gl, "debit": adv.amount, "credit": 0,
                 "currency": None, "exchange_rate": 1.0},
                {"account_id": treasury_gl, "debit": 0, "credit": adv.amount,
                 "currency": None, "exchange_rate": 1.0},
            ],
            user_id=current_user.id, branch_id=branch_id,
            source="salary_advance", source_id=advance_id,
            idempotency_key=approval_idempotency_key,
        )

        db.execute(text("""
            UPDATE salary_advances
            SET status = 'paid',
                approved_by = :uid, approved_at = NOW(),
                paid_at = NOW(),
                treasury_account_id = :tid,
                je_id = :je,
                updated_at = NOW()
            WHERE id = :id
        """), {"uid": current_user.id, "tid": payload.treasury_account_id,
               "je": je_id, "id": advance_id})

        # T1.3a: refresh treasury balance after the JE is posted.
        try:
            from utils.treasury_balance import recalc_treasury_from_gl
            recalc_treasury_from_gl(db, payload.treasury_account_id)
        except Exception:
            pass

        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="hr.advance.approve", resource_type="salary_advance",
                     resource_id=str(advance_id),
                     details={"je_id": je_id, "amount": str(adv.amount)},
                     request=request, branch_id=branch_id)
        return {"id": advance_id, "status": "paid", "je_id": je_id}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.post("/{advance_id}/cancel",
             dependencies=[Depends(require_permission("hr.loans.manage"))],
             response_model=Dict[str, Any])
def cancel_advance(advance_id: int, request: Request,
                   current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        adv = db.execute(text(
            "SELECT status FROM salary_advances WHERE id = :id FOR UPDATE"
        ), {"id": advance_id}).fetchone()
        if not adv:
            raise HTTPException(**http_error(404, "advance_not_found", request))
        if adv.status not in ("pending", "approved"):
            raise HTTPException(**http_error(400, "only_pending_approved_advances_cancellable", request))
        db.execute(text(
            "UPDATE salary_advances SET status = 'cancelled', updated_at = NOW() WHERE id = :id"
        ), {"id": advance_id})
        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="hr.advance.cancel", resource_type="salary_advance",
                     resource_id=str(advance_id), request=request)
        return {"id": advance_id, "status": "cancelled"}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

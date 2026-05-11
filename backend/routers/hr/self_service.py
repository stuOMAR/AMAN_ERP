"""Employee Self-Service router — US6.

Endpoints under /hr/self-service:
  - Profile: GET/PUT own employee profile
  - Payslips: GET own payslips (from payroll_entries)
  - Leave balance: GET own leave balance
  - Leave requests: POST submit, GET list own requests
  - Manager: GET team requests, POST approve/reject
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date
import logging

from database import get_db_connection
from routers.auth import get_current_user, UserResponse, get_current_user_company
from utils.permissions import require_permission, require_module
from utils.audit import log_activity
from schemas.self_service import (
    LeaveRequestCreate, ProfileUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/hr/self-service",
    tags=["Employee Self-Service"],
    dependencies=[Depends(require_module("hr"))],
)


# --------------- helpers ------------------------------------------------

def _resolve_employee(conn, user, raise_on_missing: bool = True) -> dict | None:
    """Return employee row dict for the authenticated user. Raises 400 if not linked (unless raise_on_missing=False)."""
    uid = user.get("id") if isinstance(user, dict) else user.id
    row = conn.execute(text("""
        SELECT e.id, e.first_name, e.last_name, e.email, e.phone,
               e.department_id, e.position_id, e.branch_id,
               e.salary, e.housing_allowance, e.transport_allowance,
               e.other_allowances, e.nationality, e.hire_date,
               COALESCE(e.annual_leave_entitlement, e.annual_leave_days, 30) AS annual_leave_days,
               d.department_name, p.position_name,
               e.user_id
        FROM employees e
        LEFT JOIN departments d ON e.department_id = d.id
        LEFT JOIN employee_positions p ON e.position_id = p.id
        WHERE e.user_id = :uid
    """), {"uid": uid}).mappings().fetchone()
    if not row:
        if raise_on_missing:
            raise HTTPException(**http_error(400, "user_not_linked_employee"))
        return None
    return dict(row)


def _notify_leave(conn, recipients_sql: str, params: dict) -> None:
    """Non-blocking notification insert for leave events."""
    try:
        conn.execute(text(f"""
            INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
            {recipients_sql}
        """), params)
        conn.commit()
    except Exception:
        pass  # Non-blocking


# --------------- Profile ------------------------------------------------

@router.get("/profile", dependencies=[Depends(require_permission("hr.self_service"))], response_model=Dict[str, Any])
def get_own_profile(request: Request, 
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Get Own Profile."""
    conn = get_db_connection(company_id)
    try:
        emp = _resolve_employee(conn, current_user, raise_on_missing=False)
        if not emp:
            return {"success": True, "data": None, "message": i18n_message("no_employee_record", request)}
        return {
            "success": True,
            "data": {
                "id": emp["id"],
                "first_name": emp["first_name"],
                "last_name": emp["last_name"],
                "email": emp["email"],
                "phone": emp["phone"],
                "department": emp["department_name"],
                "position": emp["position_name"],
                "branch_id": emp["branch_id"],
                "nationality": emp["nationality"],
                "hire_date": str(emp["hire_date"]) if emp["hire_date"] else None,
            },
        }
    finally:
        conn.close()


@router.put("/profile", dependencies=[Depends(require_permission("hr.self_service"))], response_model=Dict[str, Any])
def update_own_profile(
    body: ProfileUpdateRequest,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Update Own Profile."""
    conn = get_db_connection(company_id)
    try:
        emp = _resolve_employee(conn, current_user)

        # Only allow limited self-editable fields
        sets = []
        params: dict = {"eid": emp["id"]}
        if body.phone is not None:
            sets.append("phone = :phone")
            params["phone"] = body.phone
        if body.email is not None:
            sets.append("email = :email")
            params["email"] = body.email

        if not sets:
            raise HTTPException(**http_error(400, "no_updatable_fields", request))

        conn.execute(text(f"UPDATE employees SET {', '.join(sets)} WHERE id = :eid"), params)

        # Track change via self_service_requests
        uid = current_user.get("id") if isinstance(current_user, dict) else current_user.id
        conn.execute(text("""
            INSERT INTO self_service_requests
                (employee_id, request_type, details, status, created_by, updated_by)
            VALUES (:eid, 'profile_update', :details::jsonb, 'completed', :uid, :uid)
        """), {
            "eid": emp["id"],
            "details": str(body.model_dump(exclude_none=True)).replace("'", '"'),
            "uid": str(uid),
        })
        conn.commit()

        log_activity(
            conn, user_id=uid, username=getattr(current_user, "username", "unknown"),
            action="hr.self_service.profile_update", resource_type="employee",
            resource_id=str(emp["id"]), details=body.model_dump(exclude_none=True), request=request
        )
        return {"success": True, "message": i18n_message("profile_updated", request)}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error("profile update error: %s", e, exc_info=True)
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()


# --------------- Payslips -----------------------------------------------

@router.get("/payslips", response_model=None, dependencies=[Depends(require_permission("hr.self_service"))])
def list_own_payslips(
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """List Own Payslips."""
    conn = get_db_connection(company_id)
    try:
        emp = _resolve_employee(conn, current_user, raise_on_missing=False)
        if not emp:
            return {"success": True, "data": []}
        rows = conn.execute(text("""
            SELECT pe.id, pe.employee_id,
                   CONCAT(e.first_name, ' ', e.last_name) AS employee_name,
                   pp.name AS period_name,
                   EXTRACT(MONTH FROM pp.start_date)::int AS month,
                   EXTRACT(YEAR FROM pp.start_date)::int AS year,
                   pe.basic_salary, pe.housing_allowance,
                   pe.transport_allowance, pe.other_allowances,
                   (pe.basic_salary + pe.housing_allowance + pe.transport_allowance
                    + pe.other_allowances + pe.salary_components_earning
                    + pe.overtime_amount) AS total_earnings,
                   (pe.deductions + pe.salary_components_deduction
                    + pe.gosi_employee_share + pe.violation_deduction
                    + pe.loan_deduction) AS total_deductions,
                   pe.net_salary,
                   pe.status
            FROM payroll_entries pe
            JOIN employees e ON pe.employee_id = e.id
            JOIN payroll_periods pp ON pe.period_id = pp.id
            WHERE pe.employee_id = :eid
            ORDER BY pp.start_date DESC
        """), {"eid": emp["id"]}).mappings().fetchall()

        return {"success": True, "data": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/payslips/{payslip_id}", dependencies=[Depends(require_permission("hr.self_service"))], response_model=Dict[str, Any])
def get_payslip_detail(
    payslip_id: int,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Get Payslip Detail."""
    conn = get_db_connection(company_id)
    try:
        emp = _resolve_employee(conn, current_user)
        row = conn.execute(text("""
            SELECT pe.id, pe.employee_id,
                   CONCAT(e.first_name, ' ', e.last_name) AS employee_name,
                   pp.name AS period_name,
                   EXTRACT(MONTH FROM pp.start_date)::int AS month,
                   EXTRACT(YEAR FROM pp.start_date)::int AS year,
                   pe.basic_salary, pe.housing_allowance,
                   pe.transport_allowance, pe.other_allowances,
                   (pe.basic_salary + pe.housing_allowance + pe.transport_allowance
                    + pe.other_allowances + pe.salary_components_earning
                    + pe.overtime_amount) AS total_earnings,
                   (pe.deductions + pe.salary_components_deduction
                    + pe.gosi_employee_share + pe.violation_deduction
                    + pe.loan_deduction) AS total_deductions,
                   pe.net_salary,
                   pe.status
            FROM payroll_entries pe
            JOIN employees e ON pe.employee_id = e.id
            JOIN payroll_periods pp ON pe.period_id = pp.id
            WHERE pe.id = :pid AND pe.employee_id = :eid
        """), {"pid": payslip_id, "eid": emp["id"]}).mappings().fetchone()

        if not row:
            raise HTTPException(**http_error(404, "payslip_not_found", request))

        uid = current_user.get("id") if isinstance(current_user, dict) else current_user.id
        log_activity(
            conn,
            user_id=uid,
            username=getattr(current_user, "username", "unknown"),
            action="hr.self_service.payslip_view",
            resource_type="payroll_entry",
            resource_id=str(payslip_id),
            details={"employee_id": emp["id"]},
            request=request,
        )

        return {"success": True, "data": dict(row)}
    finally:
        conn.close()


# --------------- Leave Balance ------------------------------------------

@router.get("/leave-balance", dependencies=[Depends(require_permission("hr.self_service"))], response_model=Dict[str, Any])
def get_leave_balance(
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Get Leave Balance."""
    conn = get_db_connection(company_id)
    try:
        emp = _resolve_employee(conn, current_user, raise_on_missing=False)
        if not emp:
            return {"success": True, "data": {"annual_entitlement": 0, "used_days": 0, "pending_days": 0, "remaining_days": 0, "carry_over": 0}}
        eid = emp["id"]
        entitlement = int(emp["annual_leave_days"])
        year_start = date(date.today().year, 1, 1)

        used = conn.execute(text("""
            SELECT COALESCE(SUM(end_date - start_date + 1), 0)
            FROM leave_requests
            WHERE employee_id = :eid AND status = 'approved'
              AND leave_type IN ('annual', 'سنوية')
              AND start_date >= :ys
        """), {"eid": eid, "ys": year_start}).scalar() or 0

        pending = conn.execute(text("""
            SELECT COALESCE(SUM(end_date - start_date + 1), 0)
            FROM leave_requests
            WHERE employee_id = :eid AND status = 'pending'
              AND leave_type IN ('annual', 'سنوية')
              AND start_date >= :ys
        """), {"eid": eid, "ys": year_start}).scalar() or 0

        carry = conn.execute(text("""
            SELECT COALESCE(carried_days, 0)
            FROM leave_carryover
            WHERE employee_id = :eid
            ORDER BY year DESC LIMIT 1
        """), {"eid": eid}).scalar() or 0

        remaining = entitlement + int(carry) - int(used)

        return {
            "success": True,
            "data": {
                "annual_entitlement": entitlement,
                "used_days": int(used),
                "pending_days": int(pending),
                "remaining_days": remaining,
                "carry_over": int(carry),
            },
        }
    finally:
        conn.close()


# --------------- Leave Requests -----------------------------------------

@router.post("/leave-request", dependencies=[Depends(require_permission("hr.self_service"))], response_model=Dict[str, Any])
def submit_leave_request(
    body: LeaveRequestCreate,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Submit Leave Request."""
    conn = get_db_connection(company_id)
    try:
        emp = _resolve_employee(conn, current_user)
        eid = emp["id"]
        uid = current_user.get("id") if isinstance(current_user, dict) else current_user.id

        if body.start_date > body.end_date:
            raise HTTPException(**http_error(400, "start_date_after_end", request))

        leave_days = (body.end_date - body.start_date).days + 1

        # Overlap check
        overlap = conn.execute(text("""
            SELECT id FROM leave_requests
            WHERE employee_id = :eid AND status IN ('pending', 'approved')
              AND start_date <= :end AND end_date >= :start
        """), {"eid": eid, "start": body.start_date, "end": body.end_date}).fetchone()
        if overlap:
            raise HTTPException(**http_error(400, "overlapping_leave_request", request))

        # Balance check for annual leave
        if body.leave_type in ("annual", "سنوية"):
            year_start = date(date.today().year, 1, 1)
            used = conn.execute(text("""
                SELECT COALESCE(SUM(end_date - start_date + 1), 0)
                FROM leave_requests
                WHERE employee_id = :eid AND status = 'approved'
                  AND leave_type IN ('annual', 'سنوية')
                  AND start_date >= :ys
            """), {"eid": eid, "ys": year_start}).scalar() or 0
            pending = conn.execute(text("""
                SELECT COALESCE(SUM(end_date - start_date + 1), 0)
                FROM leave_requests
                WHERE employee_id = :eid AND status = 'pending'
                  AND leave_type IN ('annual', 'سنوية')
                  AND start_date >= :ys
            """), {"eid": eid, "ys": year_start}).scalar() or 0
            carry = conn.execute(text("""
                SELECT COALESCE(carried_days, 0)
                FROM leave_carryover
                WHERE employee_id = :eid
                ORDER BY year DESC LIMIT 1
            """), {"eid": eid}).scalar() or 0
            entitlement = int(emp["annual_leave_days"])
            remaining = entitlement + int(carry) - int(used) - int(pending)
            if leave_days > remaining:
                raise HTTPException(
                    status_code=400,
                    detail=f"رصيد الإجازات السنوية غير كافٍ. المتبقي: {remaining} يوم، المطلوب: {leave_days} يوم",
                )

        # Insert leave request
        result = conn.execute(text("""
            INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, reason, status)
            VALUES (:eid, :lt, :sd, :ed, :reason, 'pending')
            RETURNING id, created_at, status
        """), {
            "eid": eid,
            "lt": body.leave_type,
            "sd": body.start_date,
            "ed": body.end_date,
            "reason": body.reason,
        }).fetchone()

        # Track via self_service_requests
        conn.execute(text("""
            INSERT INTO self_service_requests
                (employee_id, request_type, details, status, created_by, updated_by)
            VALUES (:eid, 'leave', :details::jsonb, 'pending', :uid, :uid)
        """), {
            "eid": eid,
            "details": f'{{"leave_request_id": {result.id}, "leave_type": "{body.leave_type}", "days": {leave_days}}}',
            "uid": str(uid),
        })
        conn.commit()

        log_activity(
            conn, user_id=uid, username=getattr(current_user, "username", "unknown"),
            action="hr.self_service.leave_request", resource_type="leave_request",
            resource_id=str(result.id), details={"leave_type": body.leave_type, "days": leave_days}, request=request
        )

        # Approval workflow (non-blocking)
        try:
            from utils.approval_utils import try_submit_for_approval
            approval_info = try_submit_for_approval(
                conn,
                document_type="leave_request",
                document_id=result.id,
                document_number=f"LR-{result.id}",
                amount=float(leave_days),
                submitted_by=uid,
                description=f"طلب إجازة {body.leave_type} - {leave_days} يوم",
                link="/hr/self-service/leave-requests",
            )
            if approval_info:
                conn.commit()
        except Exception:
            pass

        # Notify managers
        emp_name = f"{emp['first_name']} {emp['last_name']}"
        _notify_leave(
            conn,
            """SELECT DISTINCT u.id, 'leave_request', :title, :message, :link, FALSE, NOW()
               FROM company_users u WHERE u.is_active = TRUE AND u.role IN ('admin','superuser','manager')""",
            {
                "title": i18n_message("notif_leave_request", request),
                "message": i18n_message("leave_request_notification", request),
                "link": "/hr/self-service/team-requests",
            },
        )

        return {
            "success": True,
            "data": {
                "id": result.id,
                "employee_id": eid,
                "leave_type": body.leave_type,
                "start_date": body.start_date,
                "end_date": body.end_date,
                "days": leave_days,
                "reason": body.reason,
                "status": result.status,
                "created_at": result.created_at,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error("leave request error: %s", e, exc_info=True)
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()


@router.get("/leave-requests", dependencies=[Depends(require_permission("hr.self_service"))], response_model=Dict[str, Any])
def list_own_leave_requests(
    status: Optional[str] = None,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """List Own Leave Requests."""
    conn = get_db_connection(company_id)
    try:
        emp = _resolve_employee(conn, current_user, raise_on_missing=False)
        if not emp:
            return {"success": True, "data": []}
        q = """
            SELECT lr.id, lr.employee_id,
                   CONCAT(e.first_name, ' ', e.last_name) AS employee_name,
                   lr.leave_type, lr.start_date, lr.end_date,
                   (lr.end_date - lr.start_date + 1) AS days,
                   lr.reason, lr.status, lr.created_at
            FROM leave_requests lr
            JOIN employees e ON lr.employee_id = e.id
            WHERE lr.employee_id = :eid
        """
        params: dict = {"eid": emp["id"]}
        if status:
            q += " AND lr.status = :status"
            params["status"] = status
        q += " ORDER BY lr.created_at DESC"

        rows = conn.execute(text(q), params).mappings().fetchall()
        return {"success": True, "data": [dict(r) for r in rows]}
    finally:
        conn.close()


# --------------- Manager: Team Requests ---------------------------------

@router.get("/team-requests", dependencies=[Depends(require_permission("hr.self_service_approve"))], response_model=Dict[str, Any])
def list_team_requests(
    status: Optional[str] = "pending",
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """List leave requests from direct reports of the authenticated manager."""
    conn = get_db_connection(company_id)
    try:
        manager = _resolve_employee(conn, current_user)
        q = """
            SELECT lr.id, lr.employee_id,
                   CONCAT(e.first_name, ' ', e.last_name) AS employee_name,
                   lr.leave_type, lr.start_date, lr.end_date,
                   (lr.end_date - lr.start_date + 1) AS days,
                   lr.reason, lr.status, lr.created_at
            FROM leave_requests lr
            JOIN employees e ON lr.employee_id = e.id
            JOIN departments d ON e.department_id = d.id
            WHERE d.manager_id = :mid
        """
        params: dict = {"mid": manager["id"]}
        if status:
            q += " AND lr.status = :status"
            params["status"] = status
        q += " ORDER BY lr.created_at DESC"

        rows = conn.execute(text(q), params).mappings().fetchall()
        return {"success": True, "data": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.post("/leave-request/{request_id}/approve", dependencies=[Depends(require_permission("hr.self_service_approve"))], response_model=Dict[str, Any])
def approve_leave_request(
    request_id: int,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Approve Leave Request."""
    conn = get_db_connection(company_id)
    try:
        manager = _resolve_employee(conn, current_user)

        lr = conn.execute(text("""
            SELECT lr.id, lr.employee_id, lr.status, e.user_id AS emp_user_id,
                   CONCAT(e.first_name, ' ', e.last_name) AS emp_name,
                   lr.leave_type, lr.start_date, lr.end_date
            FROM leave_requests lr
            JOIN employees e ON lr.employee_id = e.id
            WHERE lr.id = :rid
        """), {"rid": request_id}).mappings().fetchone()

        if not lr:
            raise HTTPException(**http_error(404, "leave_request_not_found", request))
        if lr["status"] != "pending":
            raise HTTPException(status_code=400, detail=i18n_message("cannot_approve_status", request))

        conn.execute(text("""
            UPDATE leave_requests SET status = 'approved' WHERE id = :rid
        """), {"rid": request_id})

        # Update self_service_requests if linked
        conn.execute(text("""
            UPDATE self_service_requests
            SET status = 'approved', approver_id = :mid, approved_at = NOW()
            WHERE request_type = 'leave'
              AND details->>'leave_request_id' = :rid_s
              AND status = 'pending'
        """), {"mid": manager["id"], "rid_s": str(request_id)})
        conn.commit()

        uid = current_user.get("id") if isinstance(current_user, dict) else current_user.id
        log_activity(
            conn, user_id=uid, username=getattr(current_user, "username", "unknown"),
            action="hr.self_service.leave_approve", resource_type="leave_request",
            resource_id=str(request_id), details={"employee_id": lr["employee_id"]}, request=request
        )

        # Notify employee
        if lr["emp_user_id"]:
            _notify_leave(
                conn,
                "SELECT :uid, 'leave_approved', :title, :message, :link, FALSE, NOW()",
                {
                    "uid": lr["emp_user_id"],
                    "title": i18n_message("notif_leave_approved", request),
                    "message": i18n_message("leave_approved_details", request, type=lr['leave_type'], start=lr['start_date'], end=lr['end_date']),
                    "link": "/hr/self-service/leave-requests",
                },
            )

        return {"success": True, "message": i18n_message("leave_approved", request)}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error("approve error: %s", e, exc_info=True)
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()


@router.post("/leave-request/{request_id}/reject", dependencies=[Depends(require_permission("hr.self_service_approve"))], response_model=Dict[str, Any])
def reject_leave_request(
    request_id: int,
    request: Request,
    reason: Optional[str] = None,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Reject Leave Request."""
    conn = get_db_connection(company_id)
    try:
        manager = _resolve_employee(conn, current_user)

        lr = conn.execute(text("""
            SELECT lr.id, lr.employee_id, lr.status, e.user_id AS emp_user_id,
                   lr.leave_type, lr.start_date, lr.end_date
            FROM leave_requests lr
            JOIN employees e ON lr.employee_id = e.id
            WHERE lr.id = :rid
        """), {"rid": request_id}).mappings().fetchone()

        if not lr:
            raise HTTPException(**http_error(404, "leave_request_not_found", request))
        if lr["status"] != "pending":
            raise HTTPException(status_code=400, detail=i18n_message("cannot_reject_status", request))

        conn.execute(text("UPDATE leave_requests SET status = 'rejected' WHERE id = :rid"), {"rid": request_id})

        conn.execute(text("""
            UPDATE self_service_requests
            SET status = 'rejected', approver_id = :mid, approved_at = NOW(), rejection_reason = :reason
            WHERE request_type = 'leave'
              AND details->>'leave_request_id' = :rid_s
              AND status = 'pending'
        """), {"mid": manager["id"], "rid_s": str(request_id), "reason": reason})
        conn.commit()

        uid = current_user.get("id") if isinstance(current_user, dict) else current_user.id
        log_activity(
            conn, user_id=uid, username=getattr(current_user, "username", "unknown"),
            action="hr.self_service.leave_reject", resource_type="leave_request",
            resource_id=str(request_id), details={"employee_id": lr["employee_id"], "reason": reason}, request=request
        )

        # Notify employee
        if lr["emp_user_id"]:
            _notify_leave(
                conn,
                "SELECT :uid, 'leave_rejected', :title, :message, :link, FALSE, NOW()",
                {
                    "uid": lr["emp_user_id"],
                    "title": i18n_message("notif_leave_rejected", request),
                    "message": i18n_message("leave_status_update", request)
                             + (f"\nالسبب: {reason}" if reason else ""),
                    "link": "/hr/self-service/leave-requests",
                },
            )

        return {"success": True, "message": i18n_message("leave_rejected", request)}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error("reject error: %s", e, exc_info=True)
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()

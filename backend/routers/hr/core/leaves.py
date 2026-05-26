"""core sub-router — split from monolithic core.py (T6.3).

Mounted under the parent router via core/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error, i18n_message
from utils.tax_precision import require_idempotency_key
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date
from decimal import Decimal
import logging
from routers.auth import get_current_user, UserResponse, get_current_user_company
from utils.tx import transactional
from utils.permissions import branch_scope_filter, require_permission
from utils.audit import log_activity
from schemas.hr import LeaveRequestCreate, LeaveRequestResponse

logger = logging.getLogger(__name__)
_D2 = Decimal('0.01')

def _dec(v: Any) -> Decimal:
    return Decimal(str(v or 0))

router = APIRouter()

from .core import LeaveCarryoverRequest, _dec, has_permission  # noqa: E402

@router.post("/leaves", response_model=LeaveRequestResponse, dependencies=[Depends(require_permission("hr.leaves.manage"))])
def create_leave_request(raw_request: Request, request: LeaveRequestCreate, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Create Leave Request."""
    idempotency_key = require_idempotency_key(raw_request, operation="leave request")
    with transactional(company_id) as conn:
        # Check idempotency replay
        existing_leave = conn.execute(text("""
            SELECT lr.*, CONCAT(e.first_name, ' ', e.last_name) as employee_name
            FROM leave_requests lr
            JOIN employees e ON lr.employee_id = e.id
            WHERE lr.idempotency_key = :key
            LIMIT 1
        """), {"key": idempotency_key}).fetchone()
        if existing_leave:
            return dict(existing_leave._mapping)

        try:
            # Determine employee ID
            employee_id = request.employee_id
            if not employee_id:
                # Try to find employee linked to this user
                emp_res = conn.execute(text("SELECT id FROM employees WHERE user_id = :uid"), {"uid": current_user.get("id") if isinstance(current_user, dict) else current_user.id}).fetchone()
                if not emp_res:
                    raise HTTPException(**http_error(400, "user_not_linked_employee", request))
                employee_id = emp_res[0]
            else:
                # If sending explicit employee_id, must have manage permission
                if not has_permission(current_user, "hr.leaves.manage"):
                     # Check if the employee_id matches self
                     emp_res = conn.execute(text("SELECT id FROM employees WHERE user_id = :uid"), {"uid": current_user.get("id") if isinstance(current_user, dict) else current_user.id}).fetchone()
                     if not emp_res or emp_res[0] != employee_id:
                         raise HTTPException(**http_error(403, "not_authorized_leave_others", request))

            # Validate dates
            if request.start_date > request.end_date:
                raise HTTPException(**http_error(400, "start_date_after_end", request))

            leave_days = (request.end_date - request.start_date).days + 1

            # Check for overlapping leave requests
            overlap = conn.execute(text("""
                SELECT id FROM leave_requests
                WHERE employee_id = :eid
                AND status IN ('pending', 'approved')
                AND (
                     (start_date <= :end AND end_date >= :start)
                )
            """), {"eid": employee_id, "start": request.start_date, "end": request.end_date}).fetchone()

            if overlap:
                raise HTTPException(**http_error(400, "overlapping_leave_request", request))

            # Check leave balance for annual leave type
            if request.leave_type in ('annual', 'سنوية'):
                # Get total approved leave days in current year
                year_start = date(date.today().year, 1, 1)
                used_days = conn.execute(text("""
                    SELECT COALESCE(SUM(end_date - start_date + 1), 0)
                    FROM leave_requests
                    WHERE employee_id = :eid
                    AND status = 'approved'
                    AND leave_type IN ('annual', 'سنوية')
                    AND start_date >= :year_start
                """), {"eid": employee_id, "year_start": year_start}).scalar() or 0

                # Get annual leave allowance (default 21 days per Saudi labor law)
                leave_allowance = conn.execute(text("""
                    SELECT COALESCE(annual_leave_days, 21) FROM employees WHERE id = :eid
                """), {"eid": employee_id}).scalar() or 21

                remaining_balance = int(leave_allowance) - int(used_days)
                if leave_days > remaining_balance:
                    raise HTTPException(
                        status_code=400,
                        detail=f"رصيد الإجازات السنوية غير كافٍ. المتبقي: {remaining_balance} يوم، المطلوب: {leave_days} يوم"
                    )

            # Create - CORRECT TABLE NAME 'leave_requests'
            result = conn.execute(text("""
                INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, reason, status, idempotency_key)
                VALUES (:eid, :type, :start, :end, :reason, 'pending', :idempotency_key)
                RETURNING id, created_at, status
            """), {
                "eid": employee_id,
                "type": request.leave_type,
                "start": request.start_date,
                "end": request.end_date,
                "reason": request.reason,
                "idempotency_key": idempotency_key
            }).fetchone()



            # Submit for approval workflow if exists
            approval_info = None
            try:
                from utils.approval_utils import try_submit_for_approval
                user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
                approval_info = try_submit_for_approval(
                    conn,
                    document_type="leave_request",
                    document_id=result.id,
                    document_number=f"LR-{result.id}",
                    amount=str(leave_days),
                    submitted_by=user_id,
                    description=f"طلب إجازة {request.leave_type} - {leave_days} يوم",
                    link="/hr/leaves"
                )
                if approval_info:
                    conn.commit()
            except Exception:
                pass  # Non-blocking

            # Notify HR admins/superusers about new leave request
            try:
                conn.execute(text("""
                    SELECT CONCAT(first_name, ' ', last_name) as name FROM employees WHERE id = :eid
                """), {"eid": employee_id}).fetchone()
                conn.execute(text("""
                    INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                    SELECT DISTINCT u.id, 'leave_request', :title, :message, :link, FALSE, NOW()
                    FROM company_users u
                    WHERE u.is_active = TRUE
                    AND u.role IN ('admin', 'superuser')
                """), {
                    "title": i18n_message("notif_leave_request", request),
                    "message": i18n_message("leave_request_notification", request),
                    "link": "/hr/leaves"
                })
                from services.notifications.dispatcher import dispatch_user_notification

                admin_rows = conn.execute(text("""
                    SELECT DISTINCT u.id
                    FROM company_users u
                    WHERE u.is_active = TRUE
                      AND u.role IN ('admin', 'superuser')
                """)).fetchall()
                for admin in admin_rows:
                    dispatch_user_notification(
                        conn,
                        tenant_id=company_id,
                        recipient_id=admin.id,
                        event_type="hr.leave.requested",
                        channel="in_app",
                        title=i18n_message("notif_leave_request", request),
                        body=i18n_message("leave_request_notification", request),
                        feature_source="hr",
                        reference_type="leave_request",
                        reference_id=result.id,
                        link="/hr/leaves",
                        commit=False,
                    )
                conn.commit()
            except Exception:
                pass  # Non-blocking

            response = {
                "id": result.id,
                "employee_id": employee_id,
                "leave_type": request.leave_type,
                "start_date": request.start_date,
                "end_date": request.end_date,
                "reason": request.reason,
                "status": result.status,
                "created_at": result.created_at
            }
            if approval_info:
                response["approval"] = approval_info
            return response
        except Exception as e:
            pass
            logger.error("Error creating leave: %s", e)
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.get("/leaves", response_model=List[LeaveRequestResponse], dependencies=[Depends(require_permission("hr.view"))])
def list_leave_requests(branch_id: Optional[int] = None, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """List Leave Requests."""
    # Basic view permission required
    if not has_permission(current_user, "hr.leaves.view"):
        pass
        # Actually, let's enforce view permission to be safe, but typically all employees should have "hr.leaves.view" or "hr.view".
        # If strict: raise HTTPException(**http_error(403, "not_authorized", request))

    with transactional(company_id) as conn:
        is_manager = has_permission(current_user, "hr.leaves.manage")
        query = """
            SELECT l.*, e.first_name || ' ' || e.last_name as employee_name
            FROM leave_requests l
            JOIN employees e ON l.employee_id = e.id
            WHERE 1=1
        """
        params = {}

        if not is_manager:
            emp_res = conn.execute(text("SELECT id FROM employees WHERE user_id = :uid"), {"uid": current_user.get("id") if isinstance(current_user, dict) else current_user.id}).fetchone()
            if not emp_res:
                return []
            query += " AND l.employee_id = :eid"
            params["eid"] = emp_res[0]

        query += " " + branch_scope_filter(current_user, branch_id, "e.branch_id", params, branch_param="bid")
        query += " ORDER BY l.created_at DESC"

        records = conn.execute(text(query), params).fetchall()
        return [dict(row._mapping) for row in records]

@router.put("/leaves/{leave_id}/status", dependencies=[Depends(require_permission("hr.leaves.manage"))], response_model=Dict[str, Any])
def update_leave_status(request: Request, leave_id: int, status_in: str, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Update Leave Status."""
    with transactional(company_id) as conn:
        conn.execute(text("""
            UPDATE leave_requests
            SET status = :status, approved_by = :uid, updated_at = NOW()
            WHERE id = :id
        """), {"status": status_in, "uid": current_user.get("id") if isinstance(current_user, dict) else current_user.id, "id": leave_id})

        # Notify the employee about their leave update
        try:
            emp_info = conn.execute(text("""
                SELECT e.user_id, CONCAT(e.first_name, ' ', e.last_name) as name,
                       l.leave_type, l.start_date, l.end_date
                FROM employees e
                JOIN leave_requests l ON l.employee_id = e.id
                WHERE l.id = :lid
            """), {"lid": leave_id}).fetchone()
            if emp_info and emp_info.user_id:
                icon = "✅" if status_in == 'approved' else "❌"
                status_ar = "اعتُمد" if status_in == 'approved' else "رُفض"
                conn.execute(text("""
                    INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                    VALUES (:uid, 'leave_status', :title, :message, '/hr/leaves', FALSE, NOW())
                """), {
                    "uid": emp_info.user_id,
                    "title": f"{icon} طلب إجازتك {status_ar}",
                    "message": i18n_message("leave_status_update", request)
                })
                from services.notifications.dispatcher import dispatch_user_notification

                dispatch_user_notification(
                    conn,
                    tenant_id=company_id,
                    recipient_id=emp_info.user_id,
                    event_type=f"hr.leave.{status_in}",
                    channel="in_app",
                    title=f"{icon} طلب إجازتك {status_ar}",
                    body=i18n_message("leave_status_update", request),
                    feature_source="hr",
                    reference_type="leave_request",
                    reference_id=leave_id,
                    link="/hr/leaves",
                    commit=False,
                )
        except Exception:
            pass  # Non-blocking

        # Audit log
        user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
        username = current_user.get("username", "") if isinstance(current_user, dict) else getattr(current_user, "username", "")
        log_activity(conn, user_id=user_id, username=username, action="leave.status_update",
                     resource_type="leave_request", resource_id=leave_id,
                     details={"new_status": status_in})

        return {"message": i18n_message("status_updated_success", request)}


# --- End of Service Calculation ---

@router.get("/leave-balance/{emp_id}", dependencies=[Depends(require_permission("hr.view"))], response_model=Dict[str, Any])
def get_leave_balance(request: Request, emp_id: int, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Get Leave Balance."""
    with transactional(company_id) as conn:
        from datetime import datetime as dt
        emp = conn.execute(text("""
            SELECT id, first_name||' '||last_name as name, annual_leave_entitlement, branch_id
            FROM employees WHERE id=:id
        """), {"id": emp_id}).fetchone()
        # Branch access check
        if emp and current_user.role not in ['admin', 'system_admin', 'manager', 'gm']:
            if current_user.allowed_branches and emp.branch_id not in current_user.allowed_branches:
                raise HTTPException(**http_error(403, "unauthorized_employee_access", request))
        if not emp:
            raise HTTPException(**http_error(404, "employee_not_found", request))
        year = dt.now().year
        used = conn.execute(text("""
            SELECT COALESCE(SUM(days_requested),0) as used FROM leave_requests
            WHERE employee_id=:id AND status='approved' AND EXTRACT(YEAR FROM start_date)=:y
        """), {"id": emp_id, "y": year}).fetchone()
        carryover = conn.execute(text("""
            SELECT COALESCE(SUM(carried_days),0) as carried FROM leave_carryover
            WHERE employee_id=:id AND year=:y
        """), {"id": emp_id, "y": year}).fetchone()
        entitled = _dec(emp.annual_leave_entitlement) if emp.annual_leave_entitlement else Decimal('30')
        used_d = _dec(used.used)
        carried_d = _dec(carryover.carried)
        remaining = max(Decimal('0'), entitled + carried_d - used_d)
        return {
            "employee_id": emp_id, "employee_name": emp.name, "year": year,
            "balances": [{"leave_type": "annual", "entitled_days": str(entitled),
                          "used_days": str(used_d), "carried_days": str(carried_d),
                          "remaining_days": str(remaining)}]
        }


@router.post("/leave-carryover/calculate", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def calculate_leave_carryover(request: Request, data: LeaveCarryoverRequest, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Calculate Leave Carryover."""
    with transactional(company_id) as conn:
        from datetime import datetime as dt
        year = data.year or (dt.now().year - 1)
        emp = conn.execute(text("""
            SELECT id, first_name||' '||last_name as name,
                   annual_leave_entitlement, leave_carryover_max, branch_id
            FROM employees WHERE id=:id
        """), {"id": data.employee_id}).fetchone()
        if not emp:
            raise HTTPException(**http_error(404, "employee_not_found", request))
        # Branch access check
        if current_user.role not in ['admin', 'system_admin', 'manager', 'gm']:
            if current_user.allowed_branches and emp.branch_id not in current_user.allowed_branches:
                raise HTTPException(**http_error(403, "unauthorized_employee_access", request))
        used = conn.execute(text("""
            SELECT COALESCE(SUM(days_requested),0) as used FROM leave_requests
            WHERE employee_id=:id AND status='approved' AND EXTRACT(YEAR FROM start_date)=:y
        """), {"id": data.employee_id, "y": year}).fetchone()
        entitled = _dec(emp.annual_leave_entitlement) if emp.annual_leave_entitlement else Decimal('30')
        used_d = _dec(used.used)
        max_carry = _dec(emp.leave_carryover_max) if emp.leave_carryover_max else Decimal('5')
        remaining = entitled - used_d
        carried = min(max(Decimal('0'), remaining), max_carry)
        expired = max(Decimal('0'), remaining - carried)
        conn.execute(text("""
            INSERT INTO leave_carryover (employee_id,leave_type,year,entitled_days,used_days,carried_days,expired_days,max_carryover)
            VALUES (:eid,'annual',:year,:entitled,:used,:carried,:expired,:max_carry)
            ON CONFLICT (employee_id,leave_type,year) DO UPDATE SET
            entitled_days=EXCLUDED.entitled_days, used_days=EXCLUDED.used_days,
            carried_days=EXCLUDED.carried_days, expired_days=EXCLUDED.expired_days, calculated_at=NOW()
        """), {"eid": data.employee_id, "year": year, "entitled": str(entitled), "used": str(used_d),
               "carried": str(carried), "expired": str(expired), "max_carry": str(max_carry)})
        return {"employee_id": data.employee_id, "employee_name": emp.name, "year": year,
                "entitled_days": str(entitled), "used_days": str(used_d), "carried_days": str(carried), "expired_days": str(expired)}

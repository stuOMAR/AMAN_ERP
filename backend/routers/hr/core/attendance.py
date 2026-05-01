"""core sub-router — split from monolithic core.py (T6.3).

Mounted under the parent router via core/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from routers.roles import DEFAULT_ROLES
from pydantic import BaseModel
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import logging
from database import get_db_connection, hash_password
from routers.auth import get_current_user, UserResponse, get_current_user_company
from utils.tx import transactional
from repositories import EmployeeRepository
from utils.permissions import require_permission, validate_branch_access, check_permission, require_module
from utils.permissions import has_pii_access, mask_pii, mask_pii_list, EMPLOYEE_PII_FIELDS, PAYROLL_PII_FIELDS
from utils.accounting import get_mapped_account_id, get_base_currency
from utils.fiscal_lock import check_fiscal_period_open
from utils.audit import log_activity
from schemas.hr import LoanCreate, LoanResponse, EmployeeCreate, EmployeeUpdate, DepartmentCreate, DepartmentResponse, PositionCreate, PositionResponse, PayrollPeriodCreate, PayrollEntryResponse, PayrollPeriodResponse, AttendanceResponse, LeaveRequestCreate, LeaveRequestResponse, EndOfServiceRequest
from services.gl_service import create_journal_entry as gl_create_journal_entry

logger = logging.getLogger(__name__)
_D2 = Decimal('0.01')

def _dec(v: Any) -> Decimal:
    return Decimal(str(v or 0))

router = APIRouter()

from .core import _D2

@router.post("/attendance/check-in", response_model=AttendanceResponse, dependencies=[Depends(require_permission(["hr.attendance.view", "hr.attendance.manage"]))])
def check_in(current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    conn = get_db_connection(company_id)
    trans = conn.begin()
    try:
        # Get Employee ID
        emp_res = conn.execute(
            text("SELECT id FROM employees WHERE user_id = :uid"), 
            {"uid": current_user.get("id") if isinstance(current_user, dict) else current_user.id}
        ).fetchone()
        
        if not emp_res:
            raise HTTPException(status_code=404, detail="Employee not found")
        
        employee_id = emp_res[0]
        today = date.today()
        
        # Check if already checked in today (open session without checkout)
        existing = conn.execute(
            text("SELECT id, check_in, check_out FROM attendance WHERE employee_id = :eid AND date = :date ORDER BY id DESC LIMIT 1"),
            {"eid": employee_id, "date": today}
        ).fetchone()
        
        if existing and existing[1] and not existing[2]:
            raise HTTPException(status_code=400, detail="You are already checked in")
        
        # Prevent excessive check-ins on same day (max 3 sessions)
        day_count = conn.execute(
            text("SELECT COUNT(*) FROM attendance WHERE employee_id = :eid AND date = :date"),
            {"eid": employee_id, "date": today}
        ).scalar() or 0
        
        if day_count >= 3:
            raise HTTPException(status_code=400, detail="تم تجاوز الحد الأقصى لتسجيلات الحضور لهذا اليوم (3 مرات)")
            
        # Create new check-in
        new_record = conn.execute(
            text("""
                INSERT INTO attendance (employee_id, date, check_in, status)
                VALUES (:eid, :date, CURRENT_TIMESTAMP, 'present')
                RETURNING id, employee_id, date, check_in, check_out, status, notes
            """),
            {"eid": employee_id, "date": today}
        ).fetchone()
        
        trans.commit()
        
        return AttendanceResponse(
            id=new_record[0],
            employee_id=new_record[1],
            date=new_record[2],
            check_in=new_record[3],
            check_out=new_record[4],
            status=new_record[5],
            notes=new_record[6]
        )
        
    except HTTPException:
        raise
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()

@router.post("/attendance/check-out", response_model=AttendanceResponse, dependencies=[Depends(require_permission(["hr.attendance.view", "hr.attendance.manage"]))])
def check_out(
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company)
):
    conn = get_db_connection(company_id)
    trans = conn.begin()
    try:
        # Get Employee ID
        emp_res = conn.execute(
            text("SELECT id FROM employees WHERE user_id = :uid"), 
            {"uid": current_user.get("id") if isinstance(current_user, dict) else current_user.id}
        ).fetchone()
        
        if not emp_res:
            raise HTTPException(status_code=404, detail="Employee not found")
        
        employee_id = emp_res[0]
        today = date.today()
        
        # Find active check-in
        existing = conn.execute(
            text("SELECT id FROM attendance WHERE employee_id = :eid AND date = :date AND check_out IS NULL ORDER BY id DESC LIMIT 1"),
            {"eid": employee_id, "date": today}
        ).fetchone()
        
        if not existing:
            raise HTTPException(status_code=400, detail="No active check-in found for today")
            
        # Update check-out
        updated_record = conn.execute(
            text("""
                UPDATE attendance 
                SET check_out = CURRENT_TIMESTAMP 
                WHERE id = :id
                RETURNING id, employee_id, date, check_in, check_out, status, notes
            """),
            {"id": existing[0]}
        ).fetchone()
        
        trans.commit()
        
        return AttendanceResponse(
            id=updated_record[0],
            employee_id=updated_record[1],
            date=updated_record[2],
            check_in=updated_record[3],
            check_out=updated_record[4],
            status=updated_record[5],
            notes=updated_record[6]
        )
        
    except HTTPException:
        raise
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()

@router.get("/attendance/status", dependencies=[Depends(require_permission("hr.attendance.view"))], response_model=Dict[str, Any])
def get_attendance_status(
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company)
):
    with transactional(company_id) as conn:
        emp_res = conn.execute(
            text("SELECT id FROM employees WHERE user_id = :uid"), 
            {"uid": current_user.get("id") if isinstance(current_user, dict) else current_user.id}
        ).fetchone()
        
        if not emp_res:
            return {"status": "not_linked", "message": "User not linked to employee"}
            
        employee_id = emp_res[0]
        today = date.today()
        
        # Check today's records
        record = conn.execute(
            text("""
                SELECT id, check_in, check_out 
                FROM attendance 
                WHERE employee_id = :eid AND date = :date 
                ORDER BY id DESC LIMIT 1
            """),
            {"eid": employee_id, "date": today}
        ).fetchone()
        
        if not record:
            return {"status": "checked_out", "last_action": None} # Never checked in today
            
        if record[1] and not record[2]:
            return {
                "status": "checked_in", 
                "check_in_time": record[1],
                "record_id": record[0]
            }
        else:
            return {
                "status": "checked_out", 
                "check_in_time": record[1],
                "check_out_time": record[2],
                "record_id": record[0]
            }


@router.get("/attendance/history", dependencies=[Depends(require_permission("hr.attendance.view"))], response_model=List[Dict[str, Any]])
def get_attendance_history(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company)
):
    with transactional(company_id) as conn:
        emp_res = conn.execute(
            text("SELECT id FROM employees WHERE user_id = :uid"), 
            {"uid": current_user.get("id") if isinstance(current_user, dict) else current_user.id}
        ).fetchone()
        
        if not emp_res:
            return []
            
        employee_id = emp_res[0]
        
        query = "SELECT id, employee_id, date, check_in, check_out, status, notes FROM attendance WHERE employee_id = :eid"
        params = {"eid": employee_id}
        
        if start_date:
            query += " AND date >= :start"
            params["start"] = start_date
        if end_date:
            query += " AND date <= :end"
            params["end"] = end_date
            
        query += " ORDER BY date DESC, check_in DESC"
        
        records = conn.execute(text(query), params).fetchall()
        
        return [
            AttendanceResponse(
                id=r[0], employee_id=r[1], date=r[2], 
                check_in=r[3], check_out=r[4], status=r[5], notes=r[6]
            ) for r in records
        ]
        

# --- LEAVE REQUESTS ---


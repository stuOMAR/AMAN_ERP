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

@router.get("/departments", response_model=List[DepartmentResponse], dependencies=[Depends(require_permission("hr.view"))])
def list_departments(company_id: str = Depends(get_current_user_company)):
    """List Departments."""
    with transactional(company_id) as conn:
        rows = conn.execute(text("SELECT id, department_name FROM departments ORDER BY department_name")).fetchall()
        return [{"id": r.id, "department_name": r.department_name} for r in rows]

@router.post("/departments", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def create_department(request: Request, dept: DepartmentCreate, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Create Department."""
    conn = get_db_connection(company_id)
    trans = conn.begin()
    try:
        conn.execute(text("INSERT INTO departments (department_name) VALUES (:name)"), {"name": dept.department_name})
        trans.commit()
        user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
        username = current_user.get("username", "") if isinstance(current_user, dict) else getattr(current_user, "username", "")
        log_activity(conn, user_id=user_id, username=username, action="department.create",
                     resource_type="department", resource_id=0, details={"name": dept.department_name})
        return {"message": i18n_message("department_created", request)}
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()

@router.delete("/departments/{dept_id}", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def delete_department(request: Request, dept_id: int, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Delete Department."""
    conn = get_db_connection(company_id)
    trans = conn.begin()
    try:
        # Check usage via repository
        count = EmployeeRepository(conn).count(department_id=dept_id)
        if count > 0:
            raise HTTPException(**http_error(400, "cannot_delete_department_it_is_assigned_to_employe", request))

        conn.execute(text("DELETE FROM departments WHERE id = :id"), {"id": dept_id})
        trans.commit()
        user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
        username = current_user.get("username", "") if isinstance(current_user, dict) else getattr(current_user, "username", "")
        log_activity(conn, user_id=user_id, username=username, action="department.delete",
                     resource_type="department", resource_id=dept_id, details={})
        return {"message": i18n_message("department_deleted", request)}
    except HTTPException:
        raise
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()

# --- Positions ---
@router.get("/positions", response_model=List[PositionResponse], dependencies=[Depends(require_permission("hr.view"))])
def list_positions(company_id: str = Depends(get_current_user_company)):
    """List Positions."""
    with transactional(company_id) as conn:
        query = """
            SELECT p.id, p.position_name, p.department_id, d.department_name
            FROM employee_positions p
            LEFT JOIN departments d ON p.department_id = d.id
            ORDER BY p.position_name
        """
        rows = conn.execute(text(query)).fetchall()
        return [
            {
                "id": r.id, 
                "position_name": r.position_name, 
                "department_id": r.department_id,
                "department_name": r.department_name
            } 
            for r in rows
        ]

@router.post("/positions", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def create_position(request: Request, pos: PositionCreate, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Create Position."""
    conn = get_db_connection(company_id)
    trans = conn.begin()
    try:
        conn.execute(text("INSERT INTO employee_positions (position_name, department_id) VALUES (:name, :did)"), 
                     {"name": pos.position_name, "did": pos.department_id})
        trans.commit()
        user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
        username = current_user.get("username", "") if isinstance(current_user, dict) else getattr(current_user, "username", "")
        log_activity(conn, user_id=user_id, username=username, action="position.create",
                     resource_type="position", resource_id=0, details={"name": pos.position_name})
        return {"message": i18n_message("position_created", request)}
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()

@router.delete("/positions/{pos_id}", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def delete_position(request: Request, pos_id: int, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Delete Position."""
    conn = get_db_connection(company_id)
    trans = conn.begin()
    try:
        # Check usage
        count = conn.execute(text("SELECT COUNT(*) FROM employees WHERE position_id = :id"), {"id": pos_id}).scalar()
        if count > 0:
            raise HTTPException(**http_error(400, "cannot_delete_position_it_is_assigned_to_employees", request))

        conn.execute(text("DELETE FROM employee_positions WHERE id = :id"), {"id": pos_id})
        trans.commit()
        user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
        username = current_user.get("username", "") if isinstance(current_user, dict) else getattr(current_user, "username", "")
        log_activity(conn, user_id=user_id, username=username, action="position.delete",
                     resource_type="position", resource_id=pos_id, details={})
        return {"message": i18n_message("position_deleted", request)}
    except HTTPException:
        raise
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()

# --- ATTENDANCE ENDPOINTS ---


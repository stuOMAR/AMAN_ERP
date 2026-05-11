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
from utils.permissions import branch_scope_filter, require_permission, validate_branch_access, check_permission, require_module
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

from .core import ApplicationCreate, ApplicationStageUpdate, JobOpeningCreate, JobOpeningUpdate, _D2

@router.get("/recruitment/openings", dependencies=[Depends(require_permission("hr.view"))], response_model=List[Dict[str, Any]])
def list_job_openings(status: Optional[str] = None, branch_id: Optional[int] = None, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """List Job Openings."""
    with transactional(company_id) as conn:
        q = """SELECT jo.*,
                   (SELECT COUNT(*) FROM job_applications ja WHERE ja.opening_id = jo.id) as applications_count
            FROM job_openings jo WHERE 1=1"""
        params: Dict[str, Any] = {}
        if status:
            q += " AND jo.status = :status"
            params["status"] = status
        q += " " + branch_scope_filter(current_user, branch_id, "jo.branch_id", params, branch_param="bid")
        q += " ORDER BY jo.created_at DESC"
        result = conn.execute(text(q), params).fetchall()
        return [dict(row._mapping) for row in result]


@router.post("/recruitment/openings", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def create_job_opening(data: JobOpeningCreate, company_id: str = Depends(get_current_user_company), current_user: UserResponse = Depends(get_current_user)):
    """Create Job Opening."""
    with transactional(company_id) as conn:
        res = conn.execute(text("""
            INSERT INTO job_openings (title,description,requirements,employment_type,vacancies,status,closing_date,created_by)
            VALUES (:title,:desc,:req,:emp_type,:vacancies,'open',:deadline,:created_by)
            RETURNING id,title,status,vacancies,created_at
        """), {"title": data.title, "desc": data.description or "", "req": data.requirements or "",
               "emp_type": data.employment_type, "vacancies": data.positions,
               "deadline": data.deadline, "created_by": current_user.id})
        return dict(res.fetchone()._mapping)


@router.put("/recruitment/openings/{opening_id}", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def update_job_opening(opening_id: int, data: JobOpeningUpdate, company_id: str = Depends(get_current_user_company)):
    """Update Job Opening."""
    with transactional(company_id) as conn:
        fields, params = [], {"id": opening_id}
        for f, col in [("title","title"),("status","status"),("positions","vacancies"),("requirements","requirements"),("deadline","closing_date")]:
            v = getattr(data, f, None)
            if v is not None:
                fields.append(f"{col} = :{f}"); params[f] = v
        if fields:
            conn.execute(text(f"UPDATE job_openings SET {', '.join(fields)} WHERE id = :id"), params)
        return {"message": i18n_message(("updated_success", request))}


@router.get("/recruitment/openings/{opening_id}/applications", dependencies=[Depends(require_permission("hr.view"))], response_model=List[Dict[str, Any]])
def list_opening_applications(opening_id: int, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """List Opening Applications."""
    with transactional(company_id) as conn:
        # Check branch access for this opening
        if current_user.role not in ['admin', 'system_admin', 'manager', 'gm']:
            opening = conn.execute(text("SELECT branch_id FROM job_openings WHERE id=:id"), {"id": opening_id}).fetchone()
            if opening and opening.branch_id and current_user.allowed_branches:
                if opening.branch_id not in current_user.allowed_branches:
                    raise HTTPException(**http_error(403, ("unauthorized_branch_access", request)))
        result = conn.execute(text("""
            SELECT ja.*, jo.title as opening_title
            FROM job_applications ja
            JOIN job_openings jo ON ja.opening_id = jo.id
            WHERE ja.opening_id = :id
            ORDER BY ja.created_at DESC
        """), {"id": opening_id}).fetchall()
        return [dict(row._mapping) for row in result]


@router.get("/recruitment/applications", dependencies=[Depends(require_permission("hr.view"))], response_model=List[Dict[str, Any]])
def list_all_applications(branch_id: Optional[int] = None, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """List All Applications."""
    with transactional(company_id) as conn:
        q = """SELECT ja.*, jo.title as opening_title
            FROM job_applications ja
            LEFT JOIN job_openings jo ON ja.opening_id = jo.id
            WHERE 1=1"""
        params = {}
        q += " " + branch_scope_filter(current_user, branch_id, "jo.branch_id", params, branch_param="bid")
        q += " ORDER BY ja.created_at DESC"
        result = conn.execute(text(q), params).fetchall()
        return [dict(row._mapping) for row in result]


@router.post("/recruitment/applications", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def create_application(data: ApplicationCreate, company_id: str = Depends(get_current_user_company)):
    """Create Application."""
    with transactional(company_id) as conn:
        res = conn.execute(text("""
            INSERT INTO job_applications (opening_id,applicant_name,email,phone,resume_url,cover_letter,stage,status)
            VALUES (:oid,:name,:email,:phone,:resume,:cover,'applied','pending')
            RETURNING id,applicant_name,email,stage,created_at
        """), {"oid": data.job_opening_id, "name": data.applicant_name, "email": data.email,
               "phone": data.phone, "resume": data.resume_url, "cover": data.cover_letter})
        return dict(res.fetchone()._mapping)


@router.put("/recruitment/applications/{app_id}/stage", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def update_application_stage(app_id: int, data: ApplicationStageUpdate, company_id: str = Depends(get_current_user_company)):
    """Update Application Stage."""
    with transactional(company_id) as conn:
        conn.execute(text("UPDATE job_applications SET stage=:stage, updated_at=NOW() WHERE id=:id"),
                     {"stage": data.stage, "id": app_id})
        return {"message": i18n_message(("recruitment_stage_updated", request))}


# --- Leave Balance & Carryover (with branch access) ---

